foreach ($f in Get-ChildItem 'd:\SecreAI_Build\data\lang\*.json') {
    $c = Get-Content $f.FullName -Raw
    $menu_eco = if ($c -match 'rtt_eco_mode') { 'OK' } else { 'MISSING' }
    $label_eco = if ($c -match 'rtt_label_eco') { 'OK' } else { 'MISSING' }
    Write-Host "$($f.Name): menu_eco=$menu_eco  label_eco=$label_eco"
}
