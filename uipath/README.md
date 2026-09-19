# Layer 3 — the UiPath robot

The RPA half of the project: the robot that receives a routing decision from
the orchestration webhook and executes the transaction against the mock CRM.

---

## This folder is now an empty, working project

`Main.xaml` here is **deliberately blank** — one empty Sequence, no activities.
`project.json` pins **no package versions at all**. That combination opens
cleanly in any Studio version, because there is nothing to fail resolution.

You build the workflow into it by following this guide. Studio then generates
the XAML against the packages you actually have, so versions and activity
names stop being your problem.

### If you opened this folder before, clean it first

Studio cached the failed restore. **Delete these from `uipath\`** before
reopening, or you will get the same errors from the cache:

```
uipath\.local\        uipath\.objects\      uipath\.settings\
uipath\.project\      uipath\.tmh\          uipath\entry-points.json
```

Keep only `Main.xaml`, `project.json`, `README.md` and
`Main.reference.xaml.txt`. Then open `project.json` in Studio.

### About Main.reference.xaml.txt

That is the old hand-written workflow, renamed to `.txt` so **Studio cannot
try to compile it**. It is reference only: it states the robot's whole logic
in one place, which is handy to read while you build. It does not load, for
two reasons worth knowing:

- UiPath matches `project.json` versions **exactly**, and feeds differ per
  install and per Studio version, so no pinned number works everywhere. When
  restore fails, *every* activity fails with "Could not find type 'X'" and
  "BC30002: Type 'Newtonsoft.Json.Linq.JObject' is not defined".
- it uses the classic `Excel Application Scope` idiom, which Studio 26.x may
  not expose.

Do not rename it back.

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
        │                     write back, log to AuditLog
        │
        └── ESCALATE ──────►  log to EscalationQueue with the context
            (or NEED_INFO)    packet, show the Action Center handoff
```

The robot never calls Dialogflow itself. Google's API needs OAuth2 with JWT
signing, which is genuinely painful inside Studio. The webhook handles
authentication and routing; the robot deals in plain HTTP and plain JSON.

---

## Before you open Studio

1. **Start the webhook** from the repository root, in its own terminal:

   ```
   python -m orchestrator.webhook_service
   ```

   Leave it running.

2. **Check it answers.** Open <http://127.0.0.1:5000/> in a browser — you
   should get a JSON list of endpoints. Then the one that matters:

   ```
   curl -X POST http://127.0.0.1:5000/classify -H "Content-Type: application/json" -d "{\"text\":\"where is my order 4521\"}"
   ```

   You want `"route": "AUTO_RESOLVE"`. Fix that before touching Studio.

3. **Close the workbook in Excel.** It holds an exclusive lock and the
   robot's writes will fail while it is open.

---

## Create the project

New **Process** in Studio. Then **Manage Packages** and install:

- `UiPath.Excel.Activities`
- `UiPath.WebAPI.Activities`
- `UiPath.System.Activities` (usually already there)

**Take whatever version Studio offers.** Do not type a version number — that
is exactly what broke `Main.xaml`.

> **Studio 26.x:** in the Activities panel, open the filter menu and enable
> **Show Classic**. The Workbook activities this guide uses live there.

### Why Workbook activities

Everything below uses the **Workbook** versions of the Excel activities
(search "Read Range" and pick the one under *Workbook*, not *Excel*). They
take a file path directly — no `Excel Application Scope` to wrap everything
in, no delegate, and **no Excel installation required**. Fewer moving parts,
and they work across Studio versions.

---

## Variables

On the root Sequence:

| Name | Type | Default |
|---|---|---|
| `customerText` | String | |
| `webhookUrl` | String | `"http://127.0.0.1:5000/classify"` |
| `crmPath` | String | `"D:\...\data\MockCRM_ApplianceOrders.xlsx"` (full path) |
| `responseJson` | String | |
| `result` | `Newtonsoft.Json.Linq.JObject` | |
| `route`, `intent`, `action`, `orderId` | String | |
| `reasonCode`, `reasonDetail`, `suggestedResolution`, `entitiesText` | String | |
| `confidence` | Double | |
| `dtOrders`, `dtLog` | `System.Data.DataTable` | |
| `orderRow` | `System.Data.DataRow` | |
| `orderRowNumber` | Int32 | |
| `replyText`, `referenceNo`, `orderStatus` | String | |
| `orderAmount` | Double | |

> For `JObject`, use **Browse for Types** and search `JObject`
> (`Newtonsoft.Json.Linq`). Set `crmPath` as a literal full path — simplest
> thing that works.

---

## Step 1 — Get the message

**Input Dialog**
- Label: `Enter the customer's message:`
- Title: `Customer Service Bot`
- Result → `customerText`

## Step 2 — Call the webhook

**HTTP Request** (UiPath.WebAPI.Activities)
- End Point: `webhookUrl`
- Method: `POST`
- Body Format: `application/json`
- Result → `responseJson`
- Body:

  ```vb
  "{""text"": """ + customerText.Replace("""", " ") + """, ""session_id"": ""uipath-demo""}"
  ```

  The `.Replace` strips quotes the customer typed, which would break the JSON.

## Step 3 — Read the decision

**Deserialize JSON** — JsonString `responseJson`, TypeArgument `JObject`,
Output → `result`.

Then **Assign** activities:

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

## Step 4 — Read the orders

**Read Range (Workbook)**
- WorkbookPath: `crmPath`
- SheetName: `"Orders"`
- Range: `""`
- AddHeaders: ✔
- DataTable → `dtOrders`

## Step 5 — Branch

**If** — Condition: `route = "AUTO_RESOLVE"`

### THEN — the automated path

**Assign**:

```vb
orderRow = dtOrders.Select("OrderID = " + orderId).FirstOrDefault()
```

> No quotes around `orderId` — OrderID is numeric in the sheet.

**If** `orderRow IsNot Nothing` — then:

```vb
orderRowNumber = dtOrders.Rows.IndexOf(orderRow) + 2
orderStatus    = orderRow("Status").ToString
orderAmount    = Convert.ToDouble(orderRow("Amount"))
```

> The `+ 2` catches everyone: DataTable rows are 0-indexed and Excel row 1 is
> the header, so DataTable row 0 is Excel row 2.

**If** `action = "READ_STATUS"`:

```vb
replyText = "Your " + orderRow("Product").ToString + " (order " + orderId + ") is currently: " + orderStatus + "."
```

**If** `action = "PROCESS_REFUND"` →
  **If** `orderRow("RefundEligible").ToString.ToUpper = "Y"` — then:

```vb
referenceNo = "RF" + New Random().Next(1000, 9999).ToString
```

  - **Write Cell (Workbook)** → `crmPath`, `"Orders"`, Cell
    `"I" + orderRowNumber.ToString`, Value `"Refund Initiated"`
  - **Write Cell (Workbook)** → `crmPath`, `"Orders"`, Cell
    `"J" + orderRowNumber.ToString`, Value `"N"`

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

  - **Write Cell (Workbook)** → `crmPath`, `"Orders"`, Cell
    `"K" + orderRowNumber.ToString`, Value `result("new_address").ToString`

```vb
replyText = "Updated - order " + orderId + " will now be delivered to " + result("new_address").ToString + ". Your reference number is " + referenceNo + "."
```

### Then log it — three activities, not nine

1. **Read Range (Workbook)** → `crmPath`, `"AuditLog"`, Range `""`,
   AddHeaders ✔, DataTable → `dtLog`
2. **Add Data Row** → DataTable `dtLog`, ArrayRow:

   ```vb
   {DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"), orderId, intent, confidence.ToString("F4"), result("engine").ToString, action, replyText, referenceNo, "UiPath Robot"}
   ```

3. **Write Range (Workbook)** → `crmPath`, `"AuditLog"`, StartingCell `"A1"`,
   DataTable `dtLog`, AddHeaders ✔

Reading the sheet first is what gives `dtLog` the right columns, so the array
just has to match their order.

### ELSE — the escalation path

1. **Read Range (Workbook)** → `crmPath`, `"EscalationQueue"`, Range `""`,
   AddHeaders ✔, DataTable → `dtLog`
2. **Add Data Row** → DataTable `dtLog`, ArrayRow:

   ```vb
   {DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"), orderId, intent, confidence.ToString("F4"), entitiesText, reasonCode, suggestedResolution, customerText, "Pending", "Unassigned"}
   ```

3. **Write Range (Workbook)** → `crmPath`, `"EscalationQueue"`, StartingCell
   `"A1"`, DataTable `dtLog`, AddHeaders ✔

4. **Message Box** — the Action Center handoff. This is the one worth showing
   on screen:

   ```vb
   "REASON: " + reasonCode + vbCrLf + vbCrLf +
   "Customer said:" + vbCrLf + customerText + vbCrLf + vbCrLf +
   "Intent: " + intent + "   Confidence: " + confidence.ToString("F2") + vbCrLf +
   "Entities: " + entitiesText + vbCrLf + vbCrLf +
   "Why: " + reasonDetail + vbCrLf + vbCrLf +
   "SUGGESTED RESOLUTION:" + vbCrLf + suggestedResolution
   ```

5. **Assign**:

   ```vb
   replyText = If(route = "NEED_INFO", result("followup_question").ToString, "I want to make sure this is handled properly, so I am passing you to one of our agents. They will have the full details of your request - you will not need to explain it again.")
   ```

## Step 6 — Reply

**Message Box** showing `replyText`.

---

## Test messages

| Type this | Expect |
|---|---|
| `Where is my order 4521` | AUTO_RESOLVE, status read, AuditLog row |
| `i want my money back for order 4509` | AUTO_RESOLVE, Status → Refund Initiated, `RF####` |
| `Something's wrong with my stuff` | ESCALATE, low confidence, Action Center box |
| `I want a refund for order 4516` | ESCALATE on the ₹10,000 cap **despite 0.99 confidence** |
| `my washing machine arrived broken` | ESCALATE, complaints never automate |

The fourth is the one to dwell on in review: confident *and* still escalated.
That is the whole argument of the project.

Reset between runs, from the repository root:

```
python demo.py --reset
```

---

## When it goes wrong

| Symptom | Cause |
|---|---|
| `Could not establish connection` on HTTP Request | Webhook not running. Start it, check <http://127.0.0.1:5000/>. |
| 404 at `http://127.0.0.1:5000/` | Older build with no `/` route. The service is fine — use `/health`. |
| `Cannot access file ... being used by another process` | Workbook open in Excel. Close it. |
| `Unable to find package ... with version (= x.y.z)` | A pinned version not in your feed. Never type versions — install through Manage Packages. |
| `Could not find type 'X' in namespace ...` | Packages did not restore. Fix the dependency error first; every activity fails until it is fixed. |
| Can't find "Read Range (Workbook)" | Enable **Show Classic** in the Activities panel filter. |
| `String cannot be converted to OutArgument` | Hand-edited XAML. Build in Studio instead. |
| `BC30002: Type 'Newtonsoft.Json.Linq.JObject' is not defined` | Packages did not restore, so Newtonsoft is not referenced. Same root cause as above. |
| Errors persist after replacing the files | Studio cached the failed restore. Delete `.local`, `.objects`, `.settings`, `.project`, `.tmh` and `entry-points.json`, then reopen. |
| Deserialize JSON fails | The webhook returned an error body. Log `responseJson` and read it. |
| `Column 'OrderID' does not belong to table` | Read Range ran without **AddHeaders** ticked. |
| Writes land one row off | The `+ 2` is missing or was written as `+ 1`. |
| `orderRow` is Nothing for a real order | Quoting in the Select filter — numeric IDs take no quotes. |

---

## Honest status

| Piece | State |
|---|---|
| Routing contract the robot consumes | Working, 23 automated tests |
| The five robot steps | Implemented and tested in `rpa/executor.py` |
| This build guide | Written for Workbook activities, version-agnostic |
| `uipath/Main.xaml` | Empty by design — you build into it |
| `Main.reference.xaml.txt` | Reference only, renamed so Studio ignores it |

`rpa/executor.py` is the authoritative specification of robot behaviour — it
is what the test suite checks. If the guide and that file ever disagree, the
Python is right.
