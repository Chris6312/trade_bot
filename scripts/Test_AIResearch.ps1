##############################################################################
#  Test-AIResearch.ps1
#
#  Fires the premarket AI research trigger endpoint, validates the full
#  response structure, and prints a graded pick table.
#
#  Usage:
#    .\scripts\Test-AIResearch.ps1
#    .\scripts\Test-AIResearch.ps1 -BaseUrl http://localhost:8101/api/v1
#    .\scripts\Test-AIResearch.ps1 -ShowRaw
#    .\scripts\Test-AIResearch.ps1 -TimeoutSec 300
##############################################################################

param(
    [string]$BaseUrl      = "http://localhost:8101/api/v1",
    [int]   $TimeoutSec   = 240,   # OpenAI web-search can take 2-3 min
    [switch]$ShowRaw               # dump the full JSON response at the end
)

$ErrorActionPreference = "Stop"
$triggerUrl = "$BaseUrl/universe/stock/ai-research/trigger"

# ── helpers ─────────────────────────────────────────────────────────────────

function Write-Header {
    param([string]$Text, [string]$Color = "Cyan")
    Write-Host ""
    Write-Host ("─" * 70) -ForegroundColor DarkGray
    Write-Host "  $Text" -ForegroundColor $Color
    Write-Host ("─" * 70) -ForegroundColor DarkGray
}

function Write-Check {
    param([string]$Label, [bool]$Passed, [string]$Detail = "")
    $icon   = if ($Passed) { "[PASS]" } else { "[FAIL]" }
    $color  = if ($Passed) { "Green"  } else { "Red"    }
    $suffix = if ($Detail) { "  $Detail" } else { "" }
    Write-Host ("  {0,-8} {1}{2}" -f $icon, $Label, $suffix) -ForegroundColor $color
}

function Format-Price {
    param($Value)
    if ($null -eq $Value) { return "—" }
    return ("{0:N2}" -f [double]$Value)
}

function Get-RR {
    # risk-reward ratio from entry/stop/tp; returns string or "—"
    param($Entry, $Stop, $Tp)
    try {
        $risk   = [double]$Entry - [double]$Stop
        $reward = [double]$Tp    - [double]$Entry
        if ($risk -le 0) { return "—" }
        return ("{0:N1}:1" -f ($reward / $risk))
    } catch { return "—" }
}

# ── fire the trigger ─────────────────────────────────────────────────────────

Write-Header "AI Research Scan — Trigger Test" "Cyan"
Write-Host "  Endpoint : $triggerUrl"  -ForegroundColor DarkCyan
Write-Host "  Timeout  : ${TimeoutSec}s (web-search scan takes 90-180s)" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "  Sending request..." -ForegroundColor Yellow

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

try {
    $resp = Invoke-RestMethod `
        -Method Post `
        -Uri $triggerUrl `
        -ContentType "application/json" `
        -TimeoutSec $TimeoutSec
} catch [System.Net.WebException] {
    $stopwatch.Stop()
    $statusCode = [int]$_.Exception.Response.StatusCode
    $body = ""
    try {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $body   = $reader.ReadToEnd()
    } catch {}
    Write-Host ""
    Write-Host "  [FAIL] HTTP $statusCode after $([math]::Round($stopwatch.Elapsed.TotalSeconds,1))s" -ForegroundColor Red
    if ($body) {
        Write-Host "  Response body:" -ForegroundColor DarkRed
        Write-Host "  $body" -ForegroundColor DarkRed
    }
    exit 1
} catch {
    $stopwatch.Stop()
    Write-Host ""
    Write-Host "  [FAIL] Request failed after $([math]::Round($stopwatch.Elapsed.TotalSeconds,1))s" -ForegroundColor Red
    Write-Host "  $_" -ForegroundColor DarkRed
    exit 1
}

$stopwatch.Stop()
$elapsed = [math]::Round($stopwatch.Elapsed.TotalSeconds, 1)

# ── top-level validation ──────────────────────────────────────────────────────

Write-Header "Top-Level Response Checks" "Yellow"

$statusOk         = ($resp.status -eq "executed")
$tradeDate        = [string]$resp.trade_date
$tradeDateOk      = ($tradeDate -match "^\d{4}-\d{2}-\d{2}$")
$pickCount        = [int]$resp.pick_count
$pickCountOk      = ($pickCount -ge 5)   # expect at least 5 picks on a normal scan
$picksArrayOk     = ($null -ne $resp.picks -and $resp.picks.Count -gt 0)
$venueOk          = ($resp.venue -in @("alpaca", "public"))
$universeSourceOk = ($resp.universe_source -in @("ai_research", "fallback"))
$symbolsOk        = ($resp.universe_symbol_count -ge 1)

Write-Check "status = executed"          $statusOk          "got: $($resp.status)"
Write-Check "trade_date format"          $tradeDateOk       "got: $tradeDate"
Write-Check "pick_count >= 5"            $pickCountOk       "got: $pickCount"
Write-Check "picks array present"        $picksArrayOk      "count: $($resp.picks.Count)"
Write-Check "venue valid"                $venueOk           "got: $($resp.venue)"
Write-Check "universe seeded"            $universeSourceOk  "source: $($resp.universe_source), symbols: $($resp.universe_symbol_count)"
Write-Check "elapsed < ${TimeoutSec}s"   ($elapsed -lt $TimeoutSec) "${elapsed}s"

# ── per-pick field validation ─────────────────────────────────────────────────

Write-Header "Per-Pick Field Completeness" "Yellow"

$requiredFields = @(
    "symbol", "catalyst", "approximate_price",
    "entry_zone_low", "entry_zone_high",
    "stop_loss", "take_profit_primary",
    "use_trail_stop", "position_size_dollars",
    "risk_reward_note", "is_bonus_pick"
)

$totalPicks     = $resp.picks.Count
$corePicks      = @($resp.picks | Where-Object { -not $_.is_bonus_pick })
$bonusPicks     = @($resp.picks | Where-Object {       $_.is_bonus_pick })
$perfectPicks   = 0
$missingFields  = @()
$badSLPicks     = @()
$badTPPicks     = @()
$badRRPicks     = @()

foreach ($pick in $resp.picks) {
    $missing = @()
    foreach ($field in $requiredFields) {
        $val = $pick.PSObject.Properties[$field]
        if ($null -eq $val -or $null -eq $val.Value) {
            $missing += $field
        }
    }
    if ($missing.Count -eq 0) { $perfectPicks++ }
    else { $missingFields += "$($pick.symbol): $($missing -join ', ')" }

    # validate SL < price
    if ($null -ne $pick.stop_loss -and $null -ne $pick.approximate_price) {
        if ([double]$pick.stop_loss -ge [double]$pick.approximate_price) {
            $badSLPicks += $pick.symbol
        }
    }
    # validate TP > price
    if ($null -ne $pick.take_profit_primary -and $null -ne $pick.approximate_price) {
        if ([double]$pick.take_profit_primary -le [double]$pick.approximate_price) {
            $badTPPicks += $pick.symbol
        }
    }
    # validate R:R >= 1.0
    if ($null -ne $pick.stop_loss -and $null -ne $pick.take_profit_primary -and $null -ne $pick.approximate_price) {
        $risk   = [double]$pick.approximate_price - [double]$pick.stop_loss
        $reward = [double]$pick.take_profit_primary - [double]$pick.approximate_price
        if ($risk -gt 0 -and ($reward / $risk) -lt 1.0) {
            $badRRPicks += $pick.symbol
        }
    }
}

Write-Check "total picks $totalPicks"         ($totalPicks -ge 5)        "core=$($corePicks.Count) bonus=$($bonusPicks.Count)"
Write-Check "all required fields present"     ($perfectPicks -eq $totalPicks)  "$perfectPicks/$totalPicks complete"
Write-Check "SL < entry price"                ($badSLPicks.Count -eq 0)  $(if ($badSLPicks) { "bad: $($badSLPicks -join ', ')" } else { "all OK" })
Write-Check "TP > entry price"                ($badTPPicks.Count -eq 0)  $(if ($badTPPicks) { "bad: $($badTPPicks -join ', ')" } else { "all OK" })
Write-Check "R:R >= 1:1 for all picks"        ($badRRPicks.Count -eq 0)  $(if ($badRRPicks)  { "bad: $($badRRPicks -join ', ')"  } else { "all OK" })

if ($missingFields.Count -gt 0) {
    Write-Host ""
    Write-Host "  Missing fields detail:" -ForegroundColor DarkYellow
    foreach ($m in $missingFields) {
        Write-Host "    - $m" -ForegroundColor DarkYellow
    }
}

# ── pick table ────────────────────────────────────────────────────────────────

Write-Header "Pick Table  ($($resp.trade_date)  •  $($resp.venue)  •  ${elapsed}s)" "Green"

$colW = @{ sym=6; cat=32; price=8; entry=12; sl=8; tp=8; rr=6; pos=10; bonus=6 }

$hdr = "{0,-$($colW.sym)}  {1,-$($colW.cat)}  {2,$($colW.price)}  {3,-$($colW.entry)}  {4,$($colW.sl)}  {5,$($colW.tp)}  {6,$($colW.rr)}  {7,$($colW.pos)}  {8,$($colW.bonus)}" `
    -f "TICKER","CATALYST","PRICE","ENTRY ZONE","SL","TP","R:R","SIZE $","BONUS"
$sep = "-" * $hdr.Length

Write-Host "  $hdr" -ForegroundColor White
Write-Host "  $sep" -ForegroundColor DarkGray

foreach ($pick in $resp.picks) {
    $entryZone = if ($null -ne $pick.entry_zone_low -and $null -ne $pick.entry_zone_high) {
        "{0}-{1}" -f (Format-Price $pick.entry_zone_low), (Format-Price $pick.entry_zone_high)
    } else { "—" }

    $rrStr  = Get-RR $pick.approximate_price $pick.stop_loss $pick.take_profit_primary
    $bonus  = if ($pick.is_bonus_pick) { "★" } else { "" }
    $cat    = if ($pick.catalyst.Length -gt $colW.cat) { $pick.catalyst.Substring(0, $colW.cat - 1) + "…" } else { $pick.catalyst }
    $posStr = if ($null -ne $pick.position_size_dollars) { ("{0:N0}" -f [double]$pick.position_size_dollars) } else { "—" }

    $color = if ($pick.is_bonus_pick) { "DarkYellow" } else { "White" }

    $row = "  {0,-$($colW.sym)}  {1,-$($colW.cat)}  {2,$($colW.price)}  {3,-$($colW.entry)}  {4,$($colW.sl)}  {5,$($colW.tp)}  {6,$($colW.rr)}  {7,$($colW.pos)}  {8,$($colW.bonus)}" `
        -f $pick.symbol, $cat, (Format-Price $pick.approximate_price), $entryZone,
           (Format-Price $pick.stop_loss), (Format-Price $pick.take_profit_primary),
           $rrStr, $posStr, $bonus

    Write-Host $row -ForegroundColor $color
}

Write-Host "  $sep" -ForegroundColor DarkGray
Write-Host "  ★ = bonus/higher-volatility pick" -ForegroundColor DarkYellow

# ── universe symbols ──────────────────────────────────────────────────────────

Write-Header "Universe Seeded from Picks" "Cyan"
$syms = $resp.universe_symbols -join "  "
Write-Host "  Source  : $($resp.universe_source)" -ForegroundColor White
Write-Host "  Count   : $($resp.universe_symbol_count)" -ForegroundColor White
Write-Host "  Symbols : $syms" -ForegroundColor White

# ── overall result ────────────────────────────────────────────────────────────

Write-Header "Overall Result" "White"

$allChecks = @(
    $statusOk, $tradeDateOk, $pickCountOk, $picksArrayOk,
    $venueOk, $universeSourceOk, $symbolsOk,
    ($perfectPicks -eq $totalPicks),
    ($badSLPicks.Count -eq 0), ($badTPPicks.Count -eq 0), ($badRRPicks.Count -eq 0)
)
$passed = ($allChecks | Where-Object { $_ }).Count
$total  = $allChecks.Count

if ($passed -eq $total) {
    Write-Host "  ALL CHECKS PASSED  ($passed/$total)  in ${elapsed}s" -ForegroundColor Green
} else {
    Write-Host "  $passed/$total checks passed  in ${elapsed}s" -ForegroundColor Yellow
    Write-Host "  Review FAIL items above." -ForegroundColor Red
}

# ── raw JSON (optional) ───────────────────────────────────────────────────────

if ($ShowRaw) {
    Write-Header "Raw JSON Response" "DarkGray"
    $resp | ConvertTo-Json -Depth 10
}

Write-Host ""
