# 3 用 PDF 字型找回結構

## 為什麼需要
OCR 把所有看起來像標題的行都變成 `##`：藍色小標題、旁注、紅框定理名稱、
甚至例題結尾的符號，在 Markdown 裡長得一樣。但 PDF 排版時它們用的字型不同。
找出「小標題用什麼字型」，切塊時就能只在真正的小標題切開。
同樣地，習題題號常用特殊字型，可以用來認出「Exercises」標籤被 OCR 漏掉的習題。

這段是選用的：沒有原始 PDF、或書的小標題在 Markdown 裡已經有可靠標記（例如都帶 ■），
可以跳過，切塊仍能進行，只是例題的結尾會比較不準。

## 步驟
1. 字型盤點，看前 10 份有哪些字型與字級組合：
   ```bash
   .venv-mineru/bin/python $S/inspect_fonts.py pdf_split --limit 10
   ```
2. 拿 PDF 上看得到的一個小標題去查它的字型，以及它前一段（項目符號）的字型：
   ```bash
   .venv-mineru/bin/python $S/inspect_fonts.py pdf_split --limit 60 --find "The Chain Rule"
   ```
   同一段文字可能出現在目錄、章節標題、小標題，各自字型不同，要分清楚是哪一處。
3. 把特徵寫進 `book_profile.json` 的 `layout_markers`（格式見 book-profile.md），
   並在 `evidence` 寫下查到的字型組合，以及「容易混淆的其他字型」。
4. 擷取並抽查：
   ```bash
   .venv-mineru/bin/python $S/extract_layout_hints.py pdf_split \
       --profile book_profile.json --out layout_hints.json
   ```
   開幾份 PDF 數一下小標題，和 `layout_hints.json` 該份的清單比對。

## 實例（Stewart 微積分）
- 藍色小標題：`ZapfDingbatsStd` 的 ■，後面接 `MyriadPro-Semibold` 文字。
- 容易混淆：例題結尾的 ■ 是 `ZapfDingbatsITC`；紅框定理標題是 `MyriadPro-Bold`。
  只用「有 ■」判斷會把這些都當成小標題。
- 習題題號：`MyriadPro-BoldSemiCn` 9pt（如 `21.` 或 `1–4`）；正文 `TimesLTStd-Roman` 10pt。
  `with_next: true` 讓擷取結果帶上題號後的文字，切塊時用「題號＋開頭文字」比對，
  避免把正文裡的編號清單當成習題。
- 結果：195 份 PDF 擷取到 376 個小標題、2244 個習題題號。

## 注意
- 字型名稱會帶子集前綴（`ABCDEF+MyriadPro`），腳本已去除。
- 字級是「渲染後」的大小（字型大小 × 文字矩陣 × 座標矩陣），會有 ±0.3pt 誤差，
  `size` 範圍要留寬一點。
- 掃描版 PDF 沒有文字層，這段無法使用。
