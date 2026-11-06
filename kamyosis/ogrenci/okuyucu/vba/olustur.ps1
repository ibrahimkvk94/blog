# Ogrenci_KareKod_Okuyucu.xlsm dosyasini vba\ klasorundeki kodlardan uretir.
# Gerekli: Excel > Secenekler > Guven Merkezi > Makro Ayarlari >
#          "VBA proje nesne modeline erisime guven" isaretli olmali (yalnizca uretim sirasinda).
param([string]$Klasor = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$vba = Join-Path $Klasor 'vba'
$hedef = Join-Path $Klasor 'Ogrenci_KareKod_Okuyucu.xlsm'

$xl = New-Object -ComObject Excel.Application
# Koruma: kullanicinin acik Excel'ine baglandiysak hicbir sey yapma, kapatma.
if ($xl.Visible -or $xl.UserControl -or $xl.Workbooks.Count -gt 0) {
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($xl)
    throw "Acik bir Excel'e baglanildi; once tum Excel pencerelerini kapatin, sonra tekrar calistirin."
}
$xl.DisplayAlerts = $false
try {
    $wb = $xl.Workbooks.Add()
    while ($wb.Worksheets.Count -gt 1) { $wb.Worksheets.Item($wb.Worksheets.Count).Delete() }
    $ok = $wb.Worksheets.Item(1)
    $ok.Name = 'Okut'

    $vbp = $wb.VBProject
    [void]$vbp.VBComponents.Import((Join-Path $vba 'KareKodOku.bas'))
    [void]$vbp.VBComponents.Import((Join-Path $vba 'Kurulum.bas'))
    $vbp.VBComponents.Item($ok.CodeName).CodeModule.AddFromString([IO.File]::ReadAllText((Join-Path $vba 'Okut_sayfasi.cls.txt')))
    $vbp.VBComponents.Item($wb.CodeName).CodeModule.AddFromString([IO.File]::ReadAllText((Join-Path $vba 'ThisWorkbook.cls.txt')))

    $sonuc = $xl.Run("'" + $wb.Name + "'!Kur")
    if ($sonuc) { throw "Kurulum hatasi: $sonuc" }
    $vbp.VBComponents.Remove($vbp.VBComponents.Item('Kurulum'))

    if (Test-Path $hedef) { Remove-Item $hedef }
    $wb.SaveAs($hedef, 52)   # 52 = xlOpenXMLWorkbookMacroEnabled
    $wb.Close($false)
    "Olusturuldu: $hedef"
}
finally {
    $xl.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($xl)
}
