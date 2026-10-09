# Health-Check personal MCP prototype — #341

This separate loopback server exposes **one** read-only tool,
`get_period_evidence(start, end, domains)`, over the accepted
[health-chat-evidence-v1 reader](HEALTH_CHAT_EVIDENCE.md). It has no portal,
UI resources, plugin manifest, provider calls, runtime preparation, migrations,
profile discovery or write tools. The existing standalone exporter is unchanged.
Implementation readiness and a successful connected ChatGPT read are separate.

## Local configuration and contract

Run `python -m healthcheck.chat_evidence_mcp` with an explicit `--profile`,
`--profile-kind` and IANA `--timezone`. The profile must already exist with this
candidate's schema. Missing/unmigrated profiles produce bounded tool errors;
the server never prepares or repairs them. Profiles inside Git checkouts or
linked worktrees are rejected. Development uses external synthetic data only;
Owner/private profiles require a separately authorized Owner-only runner.

The profile path, classification, evaluation timezone, row limit (default 50,
maximum 100) and weight cadence (default 7 days) are trusted startup settings,
never tool arguments. Classification is still an operator assertion, not verified
snapshot or current Stable identity. The initial domains are `weight` and
`context`, selected explicitly on each call. They use accepted source provenance
and current Context revisions. Garmin, Google, arbitrary source/path/SQL,
additional fields and duplicate domains are rejected. Inclusive `YYYY-MM-DD`
periods must span 1–90 days. The evaluation clock uses the configured timezone.

The result contains the same envelope as both JSON text and `structuredContent`.
The envelope's canonical hash is unchanged. The **entire serialized HTTP result**,
including both representations and escaping, is capped at 2 MiB; an over-budget
read returns `output_exceeds_byte_limit`, never a partial malformed envelope.
Choose a narrower period or a smaller local row limit. Each page retains its
`has_more`, `truncated`, usable counts and unknown/zero/missing distinctions.
Stale source evidence remains explicitly stale; a successful HTTP read does not
claim fresh collection or complete historical coverage. Original Context notes
are untrusted data, never instructions. No medical/causal interpretation is added.

`/mcp` implements stateless Streamable HTTP, JSON responses, initialize, ping,
notifications and tools/list/call (2025-06-18 only). The initial initialize POST
can omit the version header; subsequent POSTs require
`MCP-Protocol-Version: 2025-06-18`. March headers/unversioned subsequent POSTs and
JSON-RPC batches are rejected; older clients must support June to continue.
GET and DELETE return
405; no SSE stream/session store is needed for this read-only prototype. POST
bodies are capped at 8 KiB. Only one evidence read runs at a time; overlapping
reads receive 429 `evidence_busy`. The underlying reader retains its SQLite
transaction, deny-write authorizer and SQL/time budgets. The manual foreground
launcher binds only `127.0.0.1`, caps concurrent connections, disables access logs
and forwarded-header trust. No request, argument, result or Context content is
logged by the facade; responses are `Cache-Control: no-store`.

Host must be localhost/127.0.0.1. Origin is checked on every method; absent Origin
is allowed for server clients, and present Origin requires an exact startup
`--origin` allowlist entry. Do not add wildcard origins or proxy to the portal.

## Reproducible synthetic checks

From the isolated candidate checkout, with the locked development environment:

```powershell
uv run --locked python scripts/check_chat_evidence_mcp.py
```

This creates a fresh external temporary **synthetic** profile, seeds one fake
Weight observation and one synthetic Context note, tests HTTP initialization,
tool discovery/call, matching representations and unchanged DB/WAL/file fingerprints,
then cleans up its own fixture. Synthetic fixture preparation is confined to the
check script; the server has no migration/preparation path. No network listener,
public tunnel, provider call, credential or key creation occurs.
SQLite's WAL shared-memory (`healthcheck.db-shm`) reader coordination is exempt
from byte/mtime equality, as in the accepted WAL-aware reader contract; the
database, WAL and unrelated files remain covered by the fingerprint check.

Focused regressions (set the two paths to fresh external synthetic children):

```powershell
$env:HEALTHCHECK_DATA_DIR = "$env:TEMP\hc341-evidence-runtime-synthetic"
uv run --locked pytest tests/test_chat_evidence_mcp.py tests/test_chat_evidence.py --basetemp "$env:TEMP\hc341-evidence-pytest-synthetic"
```

Use fresh disposable temp paths; pytest's `--basetemp` can remove an existing
directory. Never substitute an Owner/private profile or output location.

For optional local MCP Inspector testing, retain only a synthetic fixture:

```powershell
uv run --locked python scripts/check_chat_evidence_mcp.py --keep-profile
uv run --locked python -m healthcheck.chat_evidence_mcp --profile <printed-synthetic-profile> --profile-kind synthetic --timezone UTC --origin http://localhost:6274
npx @modelcontextprotocol/inspector@latest
```

Select Streamable HTTP and `http://127.0.0.1:8787/mcp`. Use the actual Inspector
browser origin if its port differs. Initialize, list tools and call with:

```json
{"start":"2099-05-01","end":"2099-05-03","domains":["weight","context"]}
```

Inspector is an optional manual interoperability check, not evidence already
performed by the automated smoke. Stop the foreground server with Ctrl+C.

## Prepare personal ChatGPT connection over HTTPS

Official documentation checked 2026-10-09:
[personal plugin quickstart](https://developers.openai.com/plugins/quickstart),
[connection flow](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[authentication](https://developers.openai.com/plugins/build/auth),
[Streamable HTTP](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).
Personal custom MCP creation is subject to actual account/workspace permissions;
neither this code nor documentation proves that this account has that option.
ChatGPT does not dial the laptop's loopback address directly.

For a first **synthetic-only** connection, an Owner-authorized HTTPS deployment or
forwarder can route **only `/mcp`** to `http://127.0.0.1:8787/mcp`, preserving POST,
Accept and MCP-Protocol-Version. Set upstream Host to `127.0.0.1:8787`; preserve
Origin and explicitly allow the necessary exact origin. Do not forward the whole
Health-Check app. Use `https://<owner-selected-host>/mcp` as the Server URL and
No authentication only while the fixed profile is synthetic. This task starts
no HTTPS service, public tunnel or background service and supplies no credentials.

**Owner data must not use the anonymous synthetic route.** Both Owner profile
classifications fail startup unless `HEALTHCHECK_MCP_GATEWAY_TOKEN` is supplied
from an existing Owner-controlled secret outside Git. This is an internal
proxy-to-loopback bearer credential (at least 32 non-whitespace ASCII characters),
not an API key for ChatGPT. No credential/key generator is included. The server
checks it before protocol handling or any database read, for discovery as well as
calls. Do not place this secret in tool arguments, URLs, command lines or logs.

For Owner-data HTTPS, an **existing MCP-compatible OAuth gateway** must:

1. Terminate HTTPS and expose OAuth protected-resource and authorization-server
   metadata with the exact public MCP resource identifier; support ChatGPT's
   authorization-code/PKCE client flow and registration/discovery requirements.
2. Authenticate the Owner and allow only that Owner. Validate token signature,
   issuer, resource/audience, expiry and `health.evidence:read` scope on **every**
   request, including initialization/discovery; respond with standard OAuth
   challenges at the public boundary. Client mTLS alone does not authorize the user.
3. Strip the external Authorization header after validation and replace it with
   the separately supplied internal gateway bearer credential. Set upstream Host
   to loopback. Reject unvalidated requests; never give callers that credential.
4. Forward only the MCP endpoint and necessary gateway-owned OAuth metadata,
   disable content/credential logging and caches, and offer user/token revocation.

The facade advertises OAuth scope in tool metadata for Owner profiles; the gateway
implements public OAuth discovery/challenges. The facade does **not** implement an
OAuth issuer or validate ChatGPT tokens. ChatGPT cannot send arbitrary custom API
keys, so entering the internal secret into ChatGPT is not a supported shortcut.
If no suitable existing gateway is available, Owner-data HTTPS is **BLOCKED on
access setup**; keep the manual export fallback or separately evaluate Secure MCP
Tunnel. Do not expose a private profile by relabelling it synthetic. Gateway
construction, identity-provider calls/configuration, keys and public exposure are
outside this implementation assignment.

Once the chosen HTTPS endpoint and access gate have separately passed Inspector:

1. In ChatGPT Plugins select (+) → Add custom MCP server, if permitted.
2. Name it Health-Check evidence; set the HTTPS Server URL including `/mcp`.
   Choose No authentication for synthetic-only, or the gateway's OAuth flow for
   Owner data. Review consent and select Create as a plugin. No plugin manifest,
   marketplace submission or custom UI is required for this personal MCP flow.
3. Confirm discovery lists exactly `get_period_evidence` with read-only annotations.
   Install/select the plugin in a new supported chat using `@`.
4. Request the synthetic period above; verify an actual tool invocation and matching
   evidence. Test invalid domain/range, unavailable profile and access denial.
5. Owner data needs separate authorization and one explicit bounded private query.
   Confirm the expected profile assertion/range and no values in infrastructure logs.
   Stop forwarding/server, disconnect the plugin and revoke the gateway token;
   a subsequent call must fail. Revoke/replace the internal credential and restart
   the facade to invalidate that credential too; no persistent service is installed.

Local synthetic PASS, exact-candidate CI, independent privacy/transport review,
account custom-plugin entitlement, HTTPS/OAuth interoperability and connected
Owner UAT are separate evidence. Until the last steps are actually performed,
direct access is **UNVERIFIED**, never CONNECTED.
