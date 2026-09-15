"""
The mock CRM, behind the interface a real one would have.

The backend-simulation plan calls for an Excel workbook standing in for the
order database, reached through a REST-style wrapper shaped like a typical
CRM API. That is what this module is. Callers work in terms of orders and
fields, never rows and cells, so replacing this file with one that calls a
real endpoint is the only change needed to go live - the robot, the routing
layer and the audit trail are all untouched by it.

Every operation raises CrmError on failure rather than returning something
half-valid. Failed reads and writes are supposed to fall back to the human
queue, and that only works if failure is loud.
"""
import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

import config


class CrmError(RuntimeError):
    """Raised when the CRM cannot be read or written.

    Callers treat this as a signal to escalate to a human rather than to
    retry blindly or, worse, to report success.
    """


class OrderNotFound(CrmError):
    """The requested order id does not exist in the CRM."""


def _open(read_only=False):
    path = Path(config.CRM_WORKBOOK)
    if not path.exists():
        raise CrmError(
            f"CRM workbook not found at {path}. "
            f"Run: python scripts/build_mock_crm.py"
        )
    try:
        return load_workbook(path, read_only=read_only, data_only=True)
    except PermissionError as exc:
        # The single most common failure in a live demo: the workbook is
        # still open in Excel, which holds an exclusive lock.
        raise CrmError(
            f"Cannot open {path} - it is locked, most likely because the "
            f"workbook is open in Excel. Close it and retry."
        ) from exc
    except Exception as exc:
        raise CrmError(f"Cannot open {path}: {exc}") from exc


def _sheet(workbook, name):
    if name not in workbook.sheetnames:
        raise CrmError(
            f"Sheet '{name}' missing from the CRM workbook. "
            f"Run: python scripts/build_mock_crm.py"
        )
    return workbook[name]


def _headers(sheet):
    return [str(cell.value) if cell.value is not None else ""
            for cell in next(sheet.iter_rows(min_row=1, max_row=1))]


# ---------------------------------------------------------------------------
# Reads  ~  GET /orders/{id}
# ---------------------------------------------------------------------------
def get_order(order_id):
    """Return one order as a dict. Raises OrderNotFound if it isn't there."""
    order_id = str(order_id).strip()
    workbook = _open(read_only=True)
    try:
        sheet = _sheet(workbook, config.SHEET_ORDERS)
        headers = _headers(sheet)
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row[0] is None:
                continue
            if str(row[0]).strip() == order_id:
                return {
                    header: value
                    for header, value in zip(headers, row)
                }
        raise OrderNotFound(f"Order {order_id} not found in the CRM.")
    finally:
        workbook.close()


def list_orders(category=None):
    """Return every order, optionally filtered by appliance category."""
    workbook = _open(read_only=True)
    try:
        sheet = _sheet(workbook, config.SHEET_ORDERS)
        headers = _headers(sheet)
        orders = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row[0] is None:
                continue
            order = dict(zip(headers, row))
            if category and str(order.get("Category", "")).lower() != category.lower():
                continue
            orders.append(order)
        return orders
    finally:
        workbook.close()


# ---------------------------------------------------------------------------
# Writes  ~  PATCH /orders/{id}
# ---------------------------------------------------------------------------
def update_order(order_id, updates):
    """Update named fields on one order. Returns the updated order.

    The workbook is backed up before writing, so a crash mid-write cannot
    take the demo data with it.
    """
    order_id = str(order_id).strip()
    if not updates:
        return get_order(order_id)

    path = Path(config.CRM_WORKBOOK)
    backup = path.with_suffix(".bak.xlsx")
    try:
        shutil.copy2(path, backup)
    except OSError:
        # A missing backup is not worth failing the transaction over, but it
        # is worth not pretending we made one.
        backup = None

    workbook = _open()
    try:
        sheet = _sheet(workbook, config.SHEET_ORDERS)
        headers = _headers(sheet)

        unknown = set(updates) - set(headers)
        if unknown:
            raise CrmError(
                f"Unknown CRM field(s): {', '.join(sorted(unknown))}. "
                f"Valid fields: {', '.join(headers)}"
            )

        for row_index in range(2, sheet.max_row + 1):
            cell_value = sheet.cell(row=row_index, column=1).value
            if cell_value is None or str(cell_value).strip() != order_id:
                continue
            for field, value in updates.items():
                sheet.cell(
                    row=row_index, column=headers.index(field) + 1
                ).value = value
            workbook.save(path)
            return get_order(order_id)

        raise OrderNotFound(f"Order {order_id} not found in the CRM.")
    except PermissionError as exc:
        raise CrmError(
            f"Cannot write to {path} - close the workbook in Excel and retry."
        ) from exc
    finally:
        workbook.close()


# ---------------------------------------------------------------------------
# Append-only logs  ~  POST /audit, POST /escalations
# ---------------------------------------------------------------------------
def _append_row(sheet_name, values_by_header):
    path = Path(config.CRM_WORKBOOK)
    workbook = _open()
    try:
        sheet = _sheet(workbook, sheet_name)
        headers = _headers(sheet)
        sheet.append([values_by_header.get(header, "") for header in headers])
        workbook.save(path)
    except PermissionError as exc:
        raise CrmError(
            f"Cannot write to {path} - close the workbook in Excel and retry."
        ) from exc
    finally:
        workbook.close()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_audit(order_id, intent, confidence, engine, action, result,
              reference_no="", handled_by="UiPath Robot"):
    """Record an automated resolution. One row per case the robot closed."""
    _append_row(config.SHEET_AUDIT, {
        "Timestamp": _now(),
        "OrderID": order_id or "",
        "Intent": intent or "",
        "Confidence": confidence,
        "Engine": engine,
        "Action": action,
        "Result": result,
        "ReferenceNo": reference_no,
        "HandledBy": handled_by,
    })


def log_escalation(order_id, intent, confidence, entities, reason,
                   suggested_resolution, customer_message,
                   status="Pending", assigned_to="Unassigned"):
    """Queue a case for a human, with the context packet attached.

    This is the row an agent picks up. It carries the reasoning, not just the
    transcript, which is the entire point of the handoff design.
    """
    _append_row(config.SHEET_ESCALATION, {
        "Timestamp": _now(),
        "OrderID": order_id or "",
        "Intent": intent or "unclassified",
        "Confidence": confidence,
        "Entities": entities,
        "Reason": reason,
        "SuggestedResolution": suggested_resolution,
        "CustomerMessage": customer_message,
        "Status": status,
        "AssignedTo": assigned_to,
    })


def read_log(sheet_name):
    """Return the rows of AuditLog or EscalationQueue, for tests and demos."""
    workbook = _open(read_only=True)
    try:
        sheet = _sheet(workbook, sheet_name)
        headers = _headers(sheet)
        return [
            dict(zip(headers, row))
            for row in sheet.iter_rows(min_row=2, values_only=True)
            if any(value is not None for value in row)
        ]
    finally:
        workbook.close()
