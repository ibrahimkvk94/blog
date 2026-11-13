Attribute VB_Name = "Kurulum"
Option Explicit
' Bir kez calisir: "Okut" ve "Kayitlar" sayfalarini Kitap2.xlsx duzeninde hazirlar.

Public Function Kur() As String
    Dim adim As Long
    On Error GoTo Hata
    Application.EnableEvents = False
    Dim wb As Workbook, ok As Worksheet, ky As Worksheet, basliklar As Variant, i As Long

    adim = 1
    Set wb = ThisWorkbook
    adim = 2
    Set ok = wb.Worksheets("Okut")
    adim = 3
    Set ky = wb.Worksheets.Add(After:=ok)
    adim = 4
    ky.Name = Tr("Kay\itlar")

    adim = 5
    basliklar = Array(Tr("S\i\ra No"), "TC", "Ad", "Soyad", Tr("Do\gum Tarihi"), Tr("Do\gum Yeri"), _
        Tr("Anne Ad\i"), "Anne Meslek Bilgileri", Tr("Baba Ad\i"), "Baba Meslek Bilgileri", _
        Tr("Telefon Numaras\i"), "Anne Telefon", "Baba Telefon", "Ev Adresi", Tr("\OSYM Puan\i"), _
        Tr("Lise Ad\i"), Tr("Lise Program\i"))

    ' --- Kayitlar: Kitap2.xlsx ile ayni sutunlar (A..Q) ---
    adim = 6
    With ky
        adim = 7
        For i = 0 To 16
            adim = 8
            .Cells(1, i + 1).Value = basliklar(i)
        Next i
        adim = 9
        With .Range("A1:Q1")
            adim = 10
            .Font.Bold = True
            adim = 11
            .Interior.Color = RGB(20, 40, 75)
            adim = 12
            .Font.Color = RGB(255, 255, 255)
            adim = 13
            .VerticalAlignment = xlCenter
            adim = 14
            .WrapText = True
        End With
        adim = 15
        .Rows(1).RowHeight = 30
        adim = 16
        .Columns("A").ColumnWidth = 7
        adim = 17
        .Columns("B").ColumnWidth = 13
        adim = 18
        .Columns("C:D").ColumnWidth = 14
        adim = 19
        .Columns("E").ColumnWidth = 12
        adim = 20
        .Columns("F:G").ColumnWidth = 13
        adim = 21
        .Columns("H").ColumnWidth = 20
        adim = 22
        .Columns("I").ColumnWidth = 13
        adim = 23
        .Columns("J").ColumnWidth = 20
        adim = 24
        .Columns("K:M").ColumnWidth = 14
        adim = 25
        .Columns("N").ColumnWidth = 40
        adim = 26
        .Columns("O").ColumnWidth = 11
        adim = 27
        .Columns("P").ColumnWidth = 26
        adim = 28
        .Columns("Q").ColumnWidth = 18
        adim = 29
        .Columns("B:D").NumberFormat = "@"
        adim = 30
        .Columns("F:N").NumberFormat = "@"
        adim = 31
        .Columns("P:Q").NumberFormat = "@"
        adim = 32
        .Range("A1:Q1").NumberFormat = "General"
        adim = 33
        .Range("A:Q").VerticalAlignment = xlTop
    End With
    adim = 34
    ky.Activate
    adim = 35
    ActiveWindow.FreezePanes = False
    adim = 36
    ky.Range("A2").Select
    adim = 37
    ActiveWindow.FreezePanes = True

    ' --- Okut ---
    adim = 38
    With ok
        adim = 39
        .Cells.Font.Name = "Calibri"
        adim = 40
        .Columns("A").ColumnWidth = 2
        adim = 41
        .Columns("B").ColumnWidth = 24
        adim = 42
        .Columns("C").ColumnWidth = 70
        adim = 43
        .Columns("D").ColumnWidth = 2

        adim = 44
        .Range("B1").Value = Tr("\O\grenci Kare Kod Okutma")
        adim = 45
        .Range("B1").Font.Size = 18
        adim = 46
        .Range("B1").Font.Bold = True
        adim = 47
        .Range("B1").Font.Color = RGB(20, 40, 75)
        adim = 48
        .Range("B1:C1").Borders(xlEdgeBottom).Color = RGB(201, 162, 39)
        adim = 49
        .Range("B1:C1").Borders(xlEdgeBottom).Weight = xlThick
        adim = 50
        .Rows(1).RowHeight = 30

        adim = 51
        .Range("B3").Value = "Okutma"
        adim = 52
        .Range("B3").Font.Bold = True
        adim = 53
        With .Range("C3")
            adim = 54
            .NumberFormat = "@"
            adim = 55
            .Interior.Color = RGB(255, 242, 204)
            adim = 56
            .Borders.Color = RGB(201, 162, 39)
            adim = 57
            .Borders.Weight = xlMedium
            adim = 58
            .Font.Size = 9
            adim = 59
            .Font.Color = RGB(150, 150, 150)
            adim = 60
            .WrapText = False
            adim = 61
            .Locked = False
        End With
        adim = 62
        .Rows(3).RowHeight = 28
        adim = 63
        .Range("C4").Value = Tr("Bu sar\i h\ucre se\ciliyken kare kodu okutun. Okuyucu Enter'a bas\inca kay\it eklenir.")
        adim = 64
        .Range("C4").Font.Italic = True
        adim = 65
        .Range("C4").Font.Color = RGB(110, 110, 110)

        adim = 66
        .Range("B6").Value = "Durum"
        adim = 67
        .Range("B6").Font.Bold = True
        adim = 68
        .Range("C6").Value = Tr("Haz\ir. \Ilk kare kodu okutun.")
        adim = 69
        .Range("C6").Font.Bold = True
        adim = 70
        .Range("C6").WrapText = True
        adim = 71
        .Rows(6).RowHeight = 32
        adim = 72
        .Range("C6").VerticalAlignment = xlCenter

        adim = 73
        .Range("B7").Value = Tr("Kay\itl\i \o\grenci")
        adim = 74
        .Range("B7").Font.Bold = True
        adim = 75
        .Range("C7").Formula = "=MAX(0,COUNTA('" & ky.Name & "'!B:B)-1)"
        adim = 76
        .Range("C7").HorizontalAlignment = xlLeft

        adim = 77
        .Range("B9").Value = "Son okunan / bulunan kay" & ChrW(305) & "t"
        adim = 78
        .Range("B9").Font.Bold = True
        adim = 79
        .Range("B9").Font.Color = RGB(20, 40, 75)
        adim = 80
        For i = 0 To 16
            adim = 81
            .Cells(10 + i, 2).Value = basliklar(i)
            adim = 82
            .Cells(10 + i, 2).Font.Color = RGB(90, 90, 90)
        Next i
        adim = 83
        With .Range("C10:C26")
            adim = 84
            .NumberFormat = "@"
            adim = 85
            .WrapText = True
            adim = 86
            .HorizontalAlignment = xlLeft
            adim = 87
            .VerticalAlignment = xlTop
            adim = 88
            .Borders(xlInsideHorizontal).Color = RGB(220, 220, 220)
            adim = 89
            .Borders(xlEdgeBottom).Color = RGB(220, 220, 220)
            adim = 90
            .Borders(xlEdgeTop).Color = RGB(220, 220, 220)
        End With
        adim = 91
        .Range("B10:B26").VerticalAlignment = xlTop

        adim = 92
        .Range("B28").Value = Tr("Not")
        adim = 93
        .Range("B28").Font.Bold = True
        adim = 94
        .Range("C28").Value = Tr("Kay\itlar sayfas\i Kitap2.xlsx ile ayn\i s\utun d\uzenindedir; sat\irlar\i kopyalay\ip ba\ska bir dosyaya yap\i\st\irabilirsiniz. " & _
            "Ayn\i T.C. no ikinci kez okutulursa kay\it tekrar eklenmez.")
        adim = 95
        .Range("C28").WrapText = True
        adim = 96
        .Range("C28").Font.Color = RGB(110, 110, 110)
    End With

    adim = 97
    wb.Names.Add Name:="OkutmaHucresi", RefersTo:="=Okut!$C$3"
    adim = 98
    wb.Names.Add Name:="OkutmaDurum", RefersTo:="=Okut!$C$6"
    adim = 99
    wb.Names.Add Name:="SonOkunan", RefersTo:="=Okut!$C$10:$C$26"

    adim = 100
    ok.Activate
    adim = 101
    ActiveWindow.DisplayGridlines = False
    adim = 102
    ok.Range("C3").Select
    Application.EnableEvents = True
    Kur = ""
    Exit Function
Hata:
    Application.EnableEvents = True
    Kur = "HATA adim " & adim & ": " & Err.Number & " " & Err.Description
End Function
