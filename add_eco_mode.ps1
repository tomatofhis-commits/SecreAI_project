$langs = @{
    'en.json'    = 'Eco Mode'
    'de.json'    = 'Eco-Modus'
    'es.json'    = 'Modo Eco'
    'fr.json'    = "Mode Eco"
    'it.json'    = "Modalita Eco"
    'ko.json'    = "에코 모드"
    'pt.json'    = 'Modo Eco'
    'ru.json'    = "Eko-rezhim"
    'zh-CN.json' = "节能模式"
}

foreach ($fname in $langs.Keys) {
    $path = "d:\SecreAI_Build\data\lang\${fname}"
    $val  = $langs[$fname]
    $c = Get-Content $path -Raw -Encoding UTF8
    if ($c -notmatch 'rtt_eco_mode') {
        $c = $c -replace '("rtt_stop"\s*:\s*"[^"]*")', "`$1,`r`n    `"rtt_eco_mode`": `"$val`""
        [System.IO.File]::WriteAllText($path, $c, [System.Text.Encoding]::UTF8)
        Write-Host "${fname}: Added rtt_eco_mode"
    } else {
        Write-Host "${fname}: Already exists"
    }
}
Write-Host "Done."
