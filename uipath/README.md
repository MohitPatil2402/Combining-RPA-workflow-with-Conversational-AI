# Layer 3 — the UiPath robot

This folder holds the RPA half of the project: the robot that receives a
routing decision and executes the actual transaction against the mock CRM.

> **Read this first.** `Main.xaml` was written by hand, outside UiPath Studio,
> and has **not been opened in a live Studio install**. It is a head start,
> not a guarantee. Studio is strict about activity package versions, and if
> yours differ from `project.json` the file may refuse to open or show
> "Activity could not be loaded" boxes.
>
> **If that happens, do not fight it.** Delete `Main.xaml`, start a blank
> process, and follow *Build it by hand* below. It is about 30 minutes and it
> is the path that definitely works. Every expression you need is written out
> ready to paste.

---

## What the robot does

```
  Customer message
        │
        ▼
  POST /classify ───────────►  orchestration webhook (Layer 2)
        │                      returns: route, intent, confidence,
        │                               action, order_id, reason,
        ▼                               suggested_resolution
   route = ?
        │
        ├── AUTO_RESOLVE ──►  read Orders, execute the action,
        │                     write back, append to AuditLog
        │
        ├── NEED_INFO ─────►  ask the follow-up question
        │
        └── ESCALATE ──────►  append to EscalationQueue with the
                              context packet, show the Action Center
                              handoff, hand to a person
```

The robot never calls Dialogflow itself. That is deliberate: Google's API
needs OAuth2 with JWT signing, which is genuinely painful inside Studio and
would have eaten the build. The webhook handles authentication and routing,
and the robot deals in plain HTTP and plain JSON.

---

## Before you run anything

1. **Start the webhook** (from the repository root, in its own terminal):

   ```
   python -m orchestrator.webhook_service
   ```

   Leave it running. The robot calls it on every message.

2. **Confirm it answers** before opening Studio. This is the single most
   common cause of a confusing failure in Studio:

   ```
   curl http://127.0.0.1:5000/health
   curl -X POST http://127.0.0.1:5000/classify -H "Content-Type: application/json" -d "{\"text\":\"where is my order 4521\"}"
   ```

   You want `"route": "AUTO_RESOLVE"` in the second response. If you do not
   get it, fix that before touching UiPath.

3. **Close the workbook in Excel.** Excel takes an exclusive lock, and the
   robot's writes will fail while it is open.

---

## Build it by hand

Create a new **Process** in Studio. Install these packages from
**Manage Packages** (versions do not have to match `project.json` exactly —
take what your Studio offers):

- `UiPath.Excel.Activities`
- `UiPath.WebAPI.Activities`
- `UiPath.System.Activities`

### Variables

On the root Sequence, create these (Ctrl+K on a field also works):

| Name | Type | Default |
|---|---|---|
| `customerText` | String | |
| `webhookUrl` | String | `"http://127.0.0.1:5000/classify"` |
| `crmPath` | String | full path to `data\MockCRM_ApplianceOrders.xlsx` |
| `responseJson` | String | |
| `result` | `Newtonsoft.Json.Linq.JObject` | |
| `route`, `intent`, `action`, `orderId` | String | |
| `reasonCode`, `reasonDetail`, `suggestedResolution`, `entitiesText` | String | |
| `confidence` | Double | |
| `dtOrders`, `dtLog` | `System.Data.DataTable` | |
| `orderRow` | `System.Data.DataRow` | |
| `orderRowNumber`, `nextLogRow` | Int32 | |
| `replyText`, `referenceNo`, `orderStatus` | String | |
| `orderAmount` | Double | |

> For `JObject`, use **Browse for Types** and search `JObject` — it is in
> `Newtonsoft.Json.Linq`.

### Step 1 — Get the message

**Input Dialog**
- Label: `Enter the customer's message:`
- Title: `Customer Service Bot`
- Result: `customerText`

### Step 2 — Call the webhook

**HTTP Request** (from UiPath.WebAPI.Activities)
- End Point: `webhookUrl`
- Method: `POST`
- Body Format: `application/json`
- Result: `responseJson`
- Body:

  ```vb
  "{""text"": """ + customerText.Replace("""", " ") + """, ""session_id"": ""uipath-demo""}"
  ```

  The `.Replace` strips any double quotes the customer typed, which would
  otherwise break the JSON.

### Step 3 — Read the decision

**Deserialize JSON**
- JsonString: `responseJson`
- TypeArgument: `JObject`
- Output: `result`

Then a series of **Assign** activities:

```vb
route               = result("route").ToString
intent              = result("intent").ToString
action              = result("action").ToString
orderId             = result("order_id").ToString
confidence          = Convert.ToDouble(result("confidence").ToString)
reasonCode          = result("reason").ToString
reasonDetail        = result("reason_detail").ToString
suggestedResolution = result("suggested_resolution").ToString
entitiesText        = result("entities_text").ToString
```

### Step 4 — Open the CRM

**Excel Application Scope**
- WorkbookPath: `crmPath`
- Visible: `False`
- AutoSave: `True`

Everything below goes inside its body.

**Read Range** → SheetName `"Orders"`, Range `""`, AddHeaders ✔,
DataTable `dtOrders`.

### Step 5 — Branch on the route

**If** — Condition: `route = "AUTO_RESOLVE"`

#### THEN — the automated path

**Assign** — find and locate the order:

```vb
orderRow        = dtOrders.Select("OrderID = " + orderId).FirstOrDefault()
```

> No quotes around `orderId` — OrderID is numeric in the sheet. If you store
> order IDs as text, it becomes `"OrderID = '" + orderId + "'"`.

**If** `orderRow IsNot Nothing` — then:

```vb
orderRowNumber  = dtOrders.Rows.IndexOf(orderRow) + 2
orderStatus     = orderRow("Status").ToString
orderAmount     = Convert.ToDouble(orderRow("Amount"))
```

> The `+ 2` is the bit that catches people: DataTable rows are 0-indexed and
> Excel row 1 is the header, so DataTable row 0 is Excel row 2.

**If** `action = "READ_STATUS"`:

```vb
replyText = "Your " + orderRow("Product").ToString + " (order " + orderId + ") is currently: " + orderStatus + "."
```

**If** `action = "PROCESS_REFUND"`:

  **If** `orderRow("RefundEligible").ToString.ToUpper = "Y"` — then:

  ```vb
  referenceNo = "RF" + New Random().Next(1000, 9999).ToString
  ```

  - **Write Cell** → Sheet `"Orders"`, Cell `"I" + orderRowNumber.ToString`,
    Value `"Refund Initiated"`
  - **Write Cell** → Sheet `"Orders"`, Cell `"J" + orderRowNumber.ToString`,
    Value `"N"`

  ```vb
  replyText = "Done - I have processed a refund of Rs " + orderAmount.ToString("N2") + " for order " + orderId + ". Your reference number is " + referenceNo + ", and the money should be back in your account within 5-7 working days."
  ```

  Else:

  ```vb
  replyText = "Order " + orderId + " is outside our returns window, so I cannot process a refund automatically. I can raise this with an agent to review if you would like."
  ```

**If** `action = "UPDATE_ADDRESS"`:

```vb
referenceNo = "AD" + New Random().Next(1000, 9999).ToString
```

- **Write Cell** → Sheet `"Orders"`, Cell `"K" + orderRowNumber.ToString`,
  Value `result("new_address").ToString`

```vb
replyText = "Updated - order " + orderId + " will now be delivered to " + result("new_address").ToString + ". Your reference number is " + referenceNo + "."
```

**Then log it** — Read Range on `"AuditLog"` into `dtLog`, then:

```vb
nextLogRow = dtLog.Rows.Count + 2
```

Nine **Write Cell** activities on sheet `"AuditLog"`:

| Cell | Value |
|---|---|
| `"A" + nextLogRow.ToString` | `DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")` |
| `"B" + nextLogRow.ToString` | `orderId` |
| `"C" + nextLogRow.ToString` | `intent` |
| `"D" + nextLogRow.ToString` | `confidence.ToString("F4")` |
| `"E" + nextLogRow.ToString` | `result("engine").ToString` |
| `"F" + nextLogRow.ToString` | `action` |
| `"G" + nextLogRow.ToString` | `replyText` |
| `"H" + nextLogRow.ToString` | `referenceNo` |
| `"I" + nextLogRow.ToString` | `"UiPath Robot"` |

#### ELSE — the escalation path

Read Range on `"EscalationQueue"` into `dtLog`, then
`nextLogRow = dtLog.Rows.Count + 2`, then ten **Write Cell** activities on
sheet `"EscalationQueue"`:

| Cell | Value |
|---|---|
| `"A" + nextLogRow.ToString` | `DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")` |
| `"B" + nextLogRow.ToString` | `orderId` |
| `"C" + nextLogRow.ToString` | `intent` |
| `"D" + nextLogRow.ToString` | `confidence.ToString("F4")` |
| `"E" + nextLogRow.ToString` | `entitiesText` |
| `"F" + nextLogRow.ToString` | `reasonCode` |
| `"G" + nextLogRow.ToString` | `suggestedResolution` |
| `"H" + nextLogRow.ToString` | `customerText` |
| `"I" + nextLogRow.ToString` | `"Pending"` |
| `"J" + nextLogRow.ToString` | `"Unassigned"` |

Then a **Message Box** — this is the Action Center handoff, and it is the
thing worth showing on screen:

```vb
"REASON: " + reasonCode + vbCrLf + vbCrLf +
"Customer said:" + vbCrLf + customerText + vbCrLf + vbCrLf +
"Intent: " + intent + "   Confidence: " + confidence.ToString("F2") + vbCrLf +
"Entities: " + entitiesText + vbCrLf + vbCrLf +
"Why: " + reasonDetail + vbCrLf + vbCrLf +
"SUGGESTED RESOLUTION:" + vbCrLf + suggestedResolution
```

Then:

```vb
replyText = If(route = "NEED_INFO", result("followup_question").ToString, "I want to make sure this is handled properly, so I am passing you to one of our agents. They will have the full details of your request - you will not need to explain it again.")
```

### Step 6 — Reply

After the Excel scope, a **Message Box** showing `replyText`.

---

## Test messages

Run the process once per message and watch the workbook change.

| Type this | Expect |
|---|---|
| `Where is my order 4521` | AUTO_RESOLVE, status read, AuditLog row |
| `i want my money back for order 4509` | AUTO_RESOLVE, Status → Refund Initiated, `RF####` |
| `Something's wrong with my stuff` | ESCALATE, low confidence, Action Center box |
| `I want a refund for order 4516` | ESCALATE on the ₹10,000 cap **despite 0.99 confidence** |
| `my washing machine arrived broken` | ESCALATE, complaints never automate |
| `i want a refund` | NEED_INFO, asks for the order number |

The fourth one is the one to dwell on in a review. It is confident *and*
still escalated, which is the whole argument of the project: confidence
alone does not decide.

Reset between runs from the repository root:

```
python demo.py --reset
```

---

## When it goes wrong

| Symptom | Cause |
|---|---|
| `Could not establish connection` on HTTP Request | The webhook is not running. Start it and check `/health`. |
| `Cannot access file ... being used by another process` | The workbook is open in Excel. Close it. |
| Deserialize JSON fails | The webhook returned an error body. Log `responseJson` and look at it. |
| `Column 'OrderID' does not belong to table` | Read Range ran without **AddHeaders** ticked. |
| Writes land one row off | The `+ 2` is missing, or was written as `+ 1`. |
| `orderRow` is Nothing for a real order | Quoting in the Select filter — numeric IDs take no quotes. |
| Activity could not be loaded | Package version mismatch. Rebuild by hand from this guide. |

---

## Honest status

| Piece | State |
|---|---|
| Routing contract the robot consumes | Working and tested (23 automated tests) |
| The five robot steps | Implemented and tested in `rpa/executor.py` |
| `Main.xaml` | Written, valid XML, **not opened in Studio** |
| Build-by-hand guide | Complete, every expression given |

`rpa/executor.py` is the authoritative specification of robot behaviour —
it is what the test suite checks. If the XAML and that file ever disagree,
the Python is right and the XAML is the bug.
