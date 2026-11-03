# book_profile.json 欄位說明

每個欄位都可省略，省略時用 `scripts/book_profile.py` 的 DEFAULTS（適合多數英文教科書）。
正規表示式以 IGNORECASE＋MULTILINE 編譯；寫在 JSON 裡反斜線要寫兩次（`\\d`）。
完整範例：`assets/book_profile.stewart-calculus.json`。

```jsonc
{
  "book": "書名、版本、切分方式（給人看的）",
  "protected_files": ["Book-15.md"],          // 手動修過的 Markdown：OCR 與清理都不覆蓋
  "skip_files": [],                           // 切塊時整份略過（目錄頁會自動偵測，不用列）
  "cleanup": {
    "delete_line_patterns": ["Copyright 2021 Cengage Learning\\. All Rights Reserved\\."],
    "replacements": [["\\\\varliminf(?![A-Za-z])", "\\\\lim"]]
  },
  "layout_markers": [                         // 第 3 段：字型特徵（可省略整段）
    {"name": "subheading", "font": "MyriadPro-Semibold", "text": "[A-Za-z0-9]",
     "after": {"font": "ZapfDingbatsStd", "text": "^■$"}},
    {"name": "exercise_item", "font": ".*BoldSemiCn", "size": [8.7, 9.3],
     "text": "^\\d{1,3}(?:\\.|[–-]\\d{1,3})$", "with_next": true}
  ],
  "chunking": {
    "section_heading": "…(?P<section>\\d+\\.\\d+…)(?:\\s+(?P<title>[A-Z].*?))?\\s*$",
    "example_start":   "^ {0,3}(?:#{1,6}\\s*)?EXAMPLE\\s+(?P<label>\\d+[A-Z]?)\\b",
    "solution_marker": "^ {0,3}(?:#{1,6}\\s*)?SOLUTION\\b",
    "exercises_start": "^ {0,3}(?:#{1,6}\\s*)?(?:[A-H]\\s+)?EXERCISES\\s*$",
    "exercise_item":   "…(?P<number>\\d{1,3})…(?:\\s+(?P<text>.*))?$",
    "subheading_line": "^ {0,3}(?:#{1,6}\\s*)?■\\s*(?P<title>\\S.*?)\\s*$",
    "subheading_marker": "subheading",       // layout_markers 中代表小標題的 name
    "exercise_marker": "exercise_item",      // layout_markers 中代表習題題號的 name
    "toc_entry": "…(?P<section>…)(?P<star>…)?…(?P<title>…)\\s+(?P<page>\\d{1,4})…",
    "toc_lookahead": 2,                      // 用標題比對時往後看幾節
    "max_section_jump": 3,                   // 沒有目錄時，同章最多跳幾節
    "appendix_start": "^ {0,3}#{1,6}\\s*Appendix(?:es)?\\s*$",
    "appendix_toc_entry": "…(?P<section>[A-H])\\s+(?P<title>…)\\s+A(?P<page>\\d{1,3})\\s*$",
    "title_from_next_heading": true,         // 「## 1.1」後下一個標題行當節名
    "chapter_heading": "^ {0,3}#\\s+(?:Chapter\\s+\\d+…)?(?P<title>[A-Z]…)\\s*$", // 章標題；之後到第一節是 chapter_intro
    "sidebar_heading": null,                 // 框的標題，例如 "^ {0,3}#{1,6}\\s*(?:CASE HISTORY|FOCUS ON SECURITY)\\s*$"；預設關閉，區分大小寫
    "join_broken_paragraphs": true,          // 接回被分頁切斷的句子（只在強訊號時）
    "image_text": "[圖片未擷取]"              // 圖片佔位在文字塊中的寫法
  },
  "evidence": {                               // 每條規則：看到什麼、在哪、幾次
    "cleanup.delete_line_patterns[0]": "每頁頁尾的出版社版權行，整本約 950 處",
    "layout_markers.subheading": "inspect_fonts --find 'The Chain Rule'：…；容易混淆的是 …"
  }
}
```

## 必要的命名群組
- `section_heading`：`section`（必要）、`title`（選用）
- `example_start`：`label`（選用，例題編號）
- `exercise_item`：`number`（必要）、`text`（選用）
- `toc_entry`：`section`、`title`、`page`（必要）、`star`（選用）
- `appendix_toc_entry`：`section`、`title`、`page`

## 非英文或結構不同的書
例：中文教科書的「例題 3」「習題 2-1」「第三章 第二節」。改寫對應的 pattern 即可，
命名群組不變。章節編號不是 `章.節` 數字時（例如中文數字），切塊器的順序判斷
（`section_tuple` 取數字）會失效，要嘛在 pattern 裡只擷取阿拉伯數字，
要嘛依 04-chunking.md 最後一節複製腳本修改。

## evidence 怎麼寫
寫成之後的人讀得懂、能重新驗證的句子：
- 觀察：「merged-6.md 第 3 行 `## 1.1`，下一行才是節名」「整本 213 行章節編號，93 行沒有 #」
- 容易混淆的情況：「例題結尾的 ■ 是另一個字型 ZapfDingbatsITC」
- 沒查過的寫明：「附錄是否同格式：未確認」
