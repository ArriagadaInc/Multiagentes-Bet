# Script PowerShell para analizar las fuentes de datos del pipeline

Write-Host "`n======================================================================"
Write-Host " ANALISIS: FUENTES DE DATOS DEL PIPELINE"
Write-Host "=====================================================================" -ForegroundColor Cyan

# 1. ODDS
Write-Host "`n[1] THE ODDS API (pipeline_odds.json)" -ForegroundColor Yellow
Write-Host "---" 

if(Test-Path "pipeline_odds.json") {
    $odds = Get-Content pipeline_odds.json -Raw | ConvertFrom-Json
    $odds_by_comp = $odds | Group-Object -Property competition
    
    Write-Host "Total: $(($odds | Measure-Object).Count) eventos, $($odds_by_comp.Count) competiciones"
    
    foreach($comp_group in $odds_by_comp) {
        $comp = $comp_group.Name
        $count = $comp_group.Group.Count
        
        Write-Host "`n  [$comp]: $count eventos"
        $comp_group.Group | Select-Object -First 2 | ForEach-Object {
            Write-Host "    - $($_.home_team) vs $($_.away_team) | $($_.bookmakers_count) libros"
        }
    }
} else {
    Write-Host "  [X] Archivo no encontrado"
}

# 2. MATCH CONTEXTS (combina odds + stats + insights)
Write-Host "`n`n[2] MATCH CONTEXTS (pipeline_match_contexts.json)" -ForegroundColor Yellow
Write-Host "--- Aqui se juntan ODDS + Stats + Insights"

if(Test-Path "pipeline_match_contexts.json") {
    $mc = Get-Content pipeline_match_contexts.json -Raw | ConvertFrom-Json
    $mc_by_comp = $mc | Group-Object -Property competition
    
    Write-Host "Total: $(($mc | Measure-Object).Count) partidos, $($mc_by_comp.Count) competiciones"
    
    foreach($comp_group in $mc_by_comp) {
        $comp = $comp_group.Name
        $count = $comp_group.Group.Count
        
        Write-Host "`n  [$comp]: $count partidos"
        $comp_group.Group | Select-Object -First 1 | ForEach-Object {
            $h = $_.home
            $a = $_.away
            
            $h_stats = if($h.stats) { "[+Stats]" } else { "[-Stats]" }
            $a_stats = if($a.stats) { "[+Stats]" } else { "[-Stats]" }
            $h_ins = if($h.insights) { "[+Insights]" } else { "[-Insights]" }
            $a_ins = if($a.insights) { "[+Insights]" } else { "[-Insights]" }
            
            Write-Host "    - $($h.canonical_name) $h_stats $h_ins vs $($a.canonical_name) $a_stats $a_ins"
            
            if($h.stats) {
                $h_team = $h.stats.team
                $h_provider = $h.stats.provider
                Write-Host "      Home: From $h_provider -> '$h_team'"
            }
        }
    }
} else {
    Write-Host "  [X] Archivo no encontrado"
}

# 3. STATS (si existe)
Write-Host "`n`n[3] STATS (pipeline_stats.json)" -ForegroundColor Yellow
Write-Host "--- Datos de espn, football-data, uefa, fbref"

if(Test-Path "pipeline_stats.json") {
    $stats = Get-Content pipeline_stats.json -Raw | ConvertFrom-Json
    $stats_by_comp_prov = $stats | Group-Object -Property { "$($_.competition)|$($_.provider)" }
    
    Write-Host "Total: $(($stats | Measure-Object).Count) equipos"
    
    foreach($group in $stats_by_comp_prov) {
        $key_parts = $group.Name -split '\|'
        $comp = $key_parts[0]
        $provider = $key_parts[1]
        $count = $group.Group.Count
        
        Write-Host "`n  [$comp] $provider.toUpper(): $count equipos"
        $group.Group | Select-Object -First 3 | ForEach-Object {
            $team = $_.team
            $canonical = $_.canonical_name
            $pos = $_.stats.position
            
            Write-Host "    - '$team' -> Canonical: '$canonical' | Pos: $pos"
        }
    }
} else {
    Write-Host "  [X] Archivo no encontrado - puede estar siendo generado aun"
}

# 4. REAL MADRID TRACKING
Write-Host "`n`n[4] RASTREO: 'Real Madrid' en el pipeline" -ForegroundColor Yellow
Write-Host "---"

if(Test-Path "pipeline_odds.json") {
    $odds = Get-Content pipeline_odds.json -Raw | ConvertFrom-Json
    $rm_odds = $odds | Where-Object { $_.home_team -like "*real madrid*" -or $_.away_team -like "*real madrid*" }
    
    Write-Host "`n Paso 1: En ODDS"
    if($rm_odds) {
        $rm_odds | ForEach-Object {
            Write-Host "    * $($_.home_team) vs $($_.away_team) [$($_.competition)]"
        }
    } else {
        Write-Host "    (No encontrado)"
    }
}

if(Test-Path "pipeline_match_contexts.json") {
    $mc = Get-Content pipeline_match_contexts.json -Raw | ConvertFrom-Json
    $rm_mc = $mc | Where-Object { 
        ($_.home.canonical_name -like "*real madrid*") -or ($_.away.canonical_name -like "*real madrid*")
    }
    
    Write-Host "`n Paso 2: En MATCH_CONTEXTS (ya normalizado)"
    if($rm_mc) {
        $rm_mc | ForEach-Object {
            Write-Host "    * $($_.match_date): $($_.home.canonical_name) vs $($_.away.canonical_name)"
            if($_.home.stats) {
                Write-Host "      Home stats (original team): '$($_.home.stats.team)' from $($_.home.stats.provider)"
            }
        }
    } else {
        Write-Host "    (No encontrado)"
    }
}

Write-Host "`n`n======================================================================"
Write-Host " FIN DEL ANALISIS"
Write-Host "======================================================================" -ForegroundColor Cyan
