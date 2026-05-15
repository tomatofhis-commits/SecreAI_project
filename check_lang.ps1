foreach ($f in Get-ChildItem 'd:\SecreAI_Build\data\lang\*.json') {
    $c = Get-Content $f.FullName -Raw
    $eco = if ($c -match 'rtt_eco_mode') { 'OK' } else { 'MISSING' }
    $sng = if ($c -match 'rtt_single_mode') { 'OK' } else { 'MISSING' }
    $cpu = if ($c -match 'rtt_label_cpu') { 'OK' } else { 'MISSING' }
    $lbl = if ($c -match 'rtt_label_single') { 'OK' } else { 'MISSING' }
    Write-Host "$($f.Name): menu_eco=$eco  menu_single=$sng  label_cpu=$cpu  label_single=$lbl"
}
