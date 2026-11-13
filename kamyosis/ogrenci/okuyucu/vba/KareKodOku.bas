Attribute VB_Name = "KareKodOku"
Option Explicit
' ---------------------------------------------------------------------------
' Ogrenci Bilgi Formu kare kodunu cozer ve "Kayitlar" sayfasina satir ekler.
' Kare kod icerigi (surum 1) yalnizca rakamdir:
'   "5201" + alanlar + 4 haneli denetim
'   karakter -> TABLO sirasi (2 hane, 00-97), alan ayiraci 98,
'   tablo disi karakter -> 99 + Unicode kod noktasi (7 hane)
'   denetim  -> h = (h*31 + rakam + 1) mod 9973
' Turkce metinler Tr() ile yazilir (kaynak kod ASCII kalsin diye).
' ---------------------------------------------------------------------------

Private Const BASLIK As String = "5201"
Private Const ALAN_SAYISI As Long = 16
Private mTablo As String

Private Function Tablo() As String
    If Len(mTablo) = 0 Then
        mTablo = " ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789" & _
            ChrW(199) & ChrW(286) & ChrW(304) & ChrW(214) & ChrW(350) & ChrW(220) & _
            ChrW(231) & ChrW(287) & ChrW(305) & ChrW(246) & ChrW(351) & ChrW(252) & _
            ".,-/:()'" & Chr(34) & "+@#&_;!?" & vbLf & _
            ChrW(226) & ChrW(194) & ChrW(238) & ChrW(251) & "*"
    End If
    Tablo = mTablo
End Function

' \s=s-cedilla \S \i=dotless i \I=dotted I \g \G \u \U \o \O \c \C
Public Function Tr(ByVal s As String) As String
    Dim i As Long, c As String, r As String
    i = 1
    Do While i <= Len(s)
        c = Mid$(s, i, 1)
        If c = "\" And i < Len(s) Then
            i = i + 1
            Select Case Mid$(s, i, 1)
                Case "s": c = ChrW(351)
                Case "S": c = ChrW(350)
                Case "i": c = ChrW(305)
                Case "I": c = ChrW(304)
                Case "g": c = ChrW(287)
                Case "G": c = ChrW(286)
                Case "u": c = ChrW(252)
                Case "U": c = ChrW(220)
                Case "o": c = ChrW(246)
                Case "O": c = ChrW(214)
                Case "c": c = ChrW(231)
                Case "C": c = ChrW(199)
                Case Else: c = Mid$(s, i, 1)
            End Select
        End If
        r = r & c
        i = i + 1
    Loop
    Tr = r
End Function

Public Function KayitSayfasi() As Worksheet
    Set KayitSayfasi = ThisWorkbook.Worksheets(Tr("Kay\itlar"))
End Function

Public Function OkutSayfasi() As Worksheet
    Set OkutSayfasi = ThisWorkbook.Worksheets("Okut")
End Function

Private Function Denetim(ByVal s As String) As String
    Dim h As Long, i As Long
    For i = 1 To Len(s)
        h = (h * 31 + (AscW(Mid$(s, i, 1)) - 48) + 1) Mod 9973
    Next i
    Denetim = Format$(h, "0000")
End Function

Private Function KodNoktasi(ByVal cp As Long) As String
    If cp < &H10000 Then
        KodNoktasi = ChrW(cp)
    Else
        cp = cp - &H10000
        KodNoktasi = ChrW(&HD800& + cp \ &H400&) & ChrW(&HDC00& + (cp Mod &H400&))
    End If
End Function

' Hata yoksa "" dondurur; alanlar(0..15) doldurulur.
Public Function Coz(ByVal ham As String, ByRef alanlar() As String) As String
    Dim s As String, i As Long, c As String, k As Long, n As Long, son As Long, t As String

    For i = 1 To Len(ham)
        c = Mid$(ham, i, 1)
        If c >= "0" And c <= "9" Then s = s & c
    Next i

    If Len(s) < 8 Or Left$(s, 4) <> BASLIK Then
        Coz = Tr("Bu kare kod \O\grenci Bilgi Formu'na ait de\gil.")
        Exit Function
    End If
    If Denetim(Left$(s, Len(s) - 4)) <> Right$(s, 4) Then
        Coz = Tr("Kod eksik ya da hatal\i okundu. Tekrar okutun.")
        Exit Function
    End If

    ReDim alanlar(0 To ALAN_SAYISI - 1)
    t = Tablo()
    n = 0
    i = 5
    son = Len(s) - 4
    Do While i <= son
        If i + 1 > son Then GoTo Bozuk
        k = CLng(Mid$(s, i, 2))
        i = i + 2
        Select Case k
            Case 98
                n = n + 1
                If n >= ALAN_SAYISI Then GoTo Bozuk
            Case 99
                If i + 6 > son Then GoTo Bozuk
                alanlar(n) = alanlar(n) & KodNoktasi(CLng(Mid$(s, i, 7)))
                i = i + 7
            Case Else
                alanlar(n) = alanlar(n) & Mid$(t, k + 1, 1)
        End Select
    Loop
    If n <> ALAN_SAYISI - 1 Then GoTo Bozuk
    Coz = ""
    Exit Function
Bozuk:
    Coz = Tr("Kod i\ceri\gi beklenen bi\cimde de\gil (alan say\is\i uyu\smuyor).")
End Function

Private Sub Durum(ByVal mesaj As String, ByVal tur As Long)
    ' tur: 0 = tamam, 1 = uyari, 2 = hata
    With ThisWorkbook.Names("OkutmaDurum").RefersToRange
        .Value = mesaj
        Select Case tur
            Case 0: .Interior.Color = RGB(198, 239, 206): .Font.Color = RGB(0, 97, 0)
            Case 1: .Interior.Color = RGB(255, 235, 156): .Font.Color = RGB(156, 87, 0)
            Case Else: .Interior.Color = RGB(255, 199, 206): .Font.Color = RGB(156, 0, 6)
        End Select
    End With
    If tur > 0 Then Beep
End Sub

Private Function TarihMi(ByVal s As String, ByRef d As Date) As Boolean
    Dim p() As String
    p = Split(s, ".")
    If UBound(p) <> 2 Then Exit Function
    If Not (IsNumeric(p(0)) And IsNumeric(p(1)) And IsNumeric(p(2))) Then Exit Function
    On Error GoTo Yok
    d = DateSerial(CInt(p(2)), CInt(p(1)), CInt(p(0)))
    TarihMi = (Day(d) = CInt(p(0)) And Month(d) = CInt(p(1)))
    Exit Function
Yok:
    TarihMi = False
End Function

' Okutulan metni isler: cozer, ayni TC varsa eklemez, yoksa yeni satir ekler.
Public Sub KodIsle(ByVal metin As String)
    Dim a() As String, hata As String, ws As Worksheet, bul As Range
    Dim satir As Long, sira As Long, i As Long, sut As Long, d As Date

    hata = Coz(metin, a)
    If Len(hata) > 0 Then
        Durum hata, 2
        Exit Sub
    End If

    Set ws = KayitSayfasi()
    If Len(a(0)) > 0 Then
        Set bul = ws.Range("B2:B" & ws.Rows.Count).Find(What:=a(0), LookIn:=xlValues, LookAt:=xlWhole, MatchCase:=False)
        If Not bul Is Nothing Then
            Durum Tr("Bu T.C. no zaten kay\itl\i (S\i\ra No ") & ws.Cells(bul.Row, 1).Value & ", " & _
                  a(1) & " " & a(2) & Tr("). Tekrar eklenmedi."), 1
            SonOkunan ws, bul.Row
            Exit Sub
        End If
    End If

    satir = ws.Cells(ws.Rows.Count, 2).End(xlUp).Row + 1
    If ws.Cells(ws.Rows.Count, 1).End(xlUp).Row + 1 > satir Then satir = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row + 1
    If satir < 2 Then satir = 2
    sira = Application.WorksheetFunction.Max(ws.Range("A2:A" & ws.Rows.Count)) + 1

    ws.Cells(satir, 1).Value = sira
    For i = 0 To ALAN_SAYISI - 1
        sut = i + 2
        With ws.Cells(satir, sut)
            Select Case sut
                Case 5      ' Dogum Tarihi
                    If TarihMi(a(i), d) Then
                        .NumberFormat = "dd.mm.yyyy"
                        .Value = d
                    Else
                        .NumberFormat = "@"
                        .Value = a(i)
                    End If
                Case 15     ' OSYM Puani
                    If Len(a(i)) > 0 And IsNumeric(Replace(a(i), ".", "")) Then
                        .NumberFormat = "0.00000"
                        .Value = Val(a(i))
                    Else
                        .NumberFormat = "@"
                        .Value = a(i)
                    End If
                Case Else   ' TC, telefonlar ve diger metinler: metin olarak (bastaki 0 kaybolmasin)
                    .NumberFormat = "@"
                    .Value = a(i)
            End Select
        End With
    Next i
    ws.Cells(satir, 14).WrapText = True

    Durum Tr("Kaydedildi: ") & a(1) & " " & a(2) & Tr(" (S\i\ra No ") & sira & ")", 0
    SonOkunan ws, satir
End Sub

Private Sub SonOkunan(ByVal ws As Worksheet, ByVal satir As Long)
    Dim hedef As Range, i As Long, v As Variant, s As String
    Set hedef = ThisWorkbook.Names("SonOkunan").RefersToRange
    For i = 1 To 17
        v = ws.Cells(satir, i).Value
        If VarType(v) = vbDate Then
            s = Format$(v, "dd.mm.yyyy")
        ElseIf i = 15 And IsNumeric(v) And Not IsEmpty(v) Then
            s = Format$(v, "0.00000")
        Else
            s = CStr(v)
        End If
        hedef.Cells(i, 1).NumberFormat = "@"
        hedef.Cells(i, 1).Value = s
    Next i
End Sub

' Okutma hucresini temizleyip yeniden secer.
Public Sub OkutmayaHazirla()
    On Error Resume Next
    With ThisWorkbook.Names("OkutmaHucresi").RefersToRange
        .Parent.Activate
        .NumberFormat = "@"
        .Select
    End With
End Sub
