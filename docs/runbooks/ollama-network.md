# Ollama network exposure — owner runbook (T44, AM-31)

**Decision (owner, 2026-10-07):** Ollama on port 11434 must be reachable only from loopback and from the project's containers, never from the LAN. **The agent changes no system setting**; the owner runs the commands below and attests the result.

## What was measured (2026-10-08, read-only, Task 4 step 6)

- `OLLAMA_HOST=0.0.0.0:11434` is set at **User** scope (Machine scope is empty), so Ollama currently listens on every interface (`Get-NetTCPConnection` shows the listener on `::`):

```
User: 0.0.0.0:11434
Machine:
LocalAddress LocalPort
------------ ---------
::               11434
```
- Firewall rules for Ollama (created when Windows asked at Ollama's first run, or by its installer):

```
DisplayName Enabled Direction Action         Profile
----------- ------- --------- ------         -------
ollama.exe     True   Inbound  Allow Private, Public
ollama.exe     True   Inbound  Allow Private, Public

DisplayName Enabled Direction Action         Profile
----------- ------- --------- ------         -------
ollama.exe     True   Inbound  Allow Private, Public
ollama.exe     True   Inbound  Allow Private, Public
```

- Firewall profiles (`Get-NetFirewallProfile -PolicyStore ActiveStore`):

```
Name    Enabled DefaultInboundAction
----    ------- --------------------
Domain     True                Block
Private    True                Block
Public     True                Block
```

- Source address the host sees for a container connection to 11434:

```
LocalAddress RemoteAddress
------------ -------------
127.0.0.1    127.0.0.1
```

The last measurement is the decisive one: on this machine (Docker Desktop 29.6.2, WSL2 backend) a container's connection to `host.docker.internal:11434` arrives at the host **from 127.0.0.1**, because Docker's backend process proxies it. A listener bound to loopback is therefore still reachable from containers (verified in the plan's round-2 dry run with a loopback-only test listener). The `vEthernet (WSL)` subnet never appears as a source address, so a firewall rule scoped to it would admit nothing.

## Step A (recommended) — bind Ollama to loopback

Ollama's own default is `127.0.0.1:11434`; the `0.0.0.0` value is an explicit override set in your **User** environment (measured; Machine scope is empty). Replace it at the scope where it is set — no elevation needed:

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "127.0.0.1:11434", "User")
# Confirm nothing at Machine scope overrides it (expected: empty):
[Environment]::GetEnvironmentVariable("OLLAMA_HOST", "Machine")
# Restart Ollama so it re-reads the variable: quit it from the tray icon, then start it again (or sign out and in).
```

Verify:

```powershell
# 1. Only a loopback listener remains.
Get-NetTCPConnection -LocalPort 11434 -State Listen | Select-Object LocalAddress,LocalPort
```
Expected: exactly `127.0.0.1  11434` (no `0.0.0.0` row).

```bash
# 2. Containers still reach it (Git Bash, repo root).
OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/plan_b/live/test_ollama_bridge.py -q
```
Expected: `1 passed`.

3. The LAN cannot: from another device on the same network, `curl -m 5 http://<this host's LAN IP>:11434/api/version` must be refused or time out. Record the attestation below.

With step A applied, the existing allow-any firewall rules for `ollama.exe` are harmless (nothing listens on a LAN address), but disabling them costs nothing and removes a surprise for the next person who changes `OLLAMA_HOST`:

```powershell
Get-NetFirewallApplicationFilter | Where-Object Program -like '*ollama*' | Get-NetFirewallRule | Disable-NetFirewallRule
```

## Step B (fallback) — scoped firewall rule, only if containers stop arriving from loopback

A future Docker Desktop could deliver container traffic from the WSL VM's address instead of proxying it. The symptom: step A's verification 2 fails while `Get-NetTCPConnection -LocalPort 11434 -State Established` (run during the Task 4 step 6 command) shows a non-loopback `RemoteAddress`. Then:

1. Set `OLLAMA_HOST` back to `0.0.0.0:11434` and restart Ollama.
2. In an elevated PowerShell, allow 11434 only from loopback and the **measured** source address's subnet (`Get-NetIPAddress -AddressFamily IPv4 | Where-Object InterfaceAlias -like '*WSL*'` prints the WSL adapter; on 2026-10-08 it was `172.28.32.1/20`, i.e. `172.28.32.0/20`, and this subnet can change after a reboot):

```powershell
$subnet = "<measured subnet>"
Get-NetFirewallApplicationFilter | Where-Object Program -like '*ollama*' | Get-NetFirewallRule | Disable-NetFirewallRule
Get-NetFirewallRule -DisplayName '*ollama*' | Where-Object DisplayName -notlike 'Ollama 11434*' | Disable-NetFirewallRule
New-NetFirewallRule -DisplayName "Ollama 11434 - loopback and Docker/WSL only" -Direction Inbound -Protocol TCP -LocalPort 11434 -RemoteAddress 127.0.0.1,$subnet -Action Allow -Profile Any
```
No block rule is added on purpose: an explicit Block rule wins over an Allow rule and would cut the containers off too. With the allow-any rules disabled, each profile's default inbound action (`Block` in the effective policy — confirm with `Get-NetFirewallProfile -PolicyStore ActiveStore`) refuses everyone else; loopback traffic is not filtered. After a reboot that changes the subnet: `Set-NetFirewallRule -DisplayName "Ollama 11434 - loopback and Docker/WSL only" -RemoteAddress 127.0.0.1,"<new subnet>"`.

3. Verify as in step A (listener now `0.0.0.0`, container test passes, LAN refused), and record which step is in force in the attestation.

## Attestation

| Date | Step in force (A or B) | Listener (`Get-NetTCPConnection`) | Container test | LAN test from (device) | Result |
|---|---|---|---|---|---|
| | | | | | |

## Proposed spec errata (for the owner's next revision)

AM-31 says Ollama "is reachable only from loopback and the Docker/WSL subnet" and that "the owner applies the firewall restriction". Measured on this machine, loopback alone suffices because Docker Desktop proxies container traffic from 127.0.0.1; the firewall restriction is the fallback, not the primary control. Suggested wording: "Ollama binds to loopback (`OLLAMA_HOST=127.0.0.1:11434`); containers reach it through Docker Desktop's loopback proxy (`host.docker.internal`). A firewall rule scoped to the Docker/WSL subnet is used only where container traffic arrives from that subnet."

## Rollback

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")   # the scope it was set in; then restart Ollama
Remove-NetFirewallRule -DisplayName "Ollama 11434 - loopback and Docker/WSL only" -ErrorAction SilentlyContinue
Get-NetFirewallApplicationFilter | Where-Object Program -like '*ollama*' | Get-NetFirewallRule | Enable-NetFirewallRule
```
