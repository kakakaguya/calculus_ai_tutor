# 4 依章節、小標題、例題切塊

## 切成什麼
| kind | 範圍 | 用途 |
|---|---|---|
| `section_text` | 從章節標題或一個小標題開始，到下一個邊界 | 觀念說明，主要的檢索與回答對象 |
| `example` | `EXAMPLE n` 到下一個例題、小標題、章節或習題；含完整解答 | 解題示範，掛在前一塊 section_text 底下 |
| `exercises` | 習題區，同一節的連續習題併成一塊 | 通常不檢索（沒有解答，容易誤導），留給出題用 |
| `section_text`＋`label: chapter_intro` | 章標題（MinerU 寫成單一個 `#`）到第一節之間的概述 | 一章的總覽；`section` 是章號（例如 `1`） |
| `sidebar` | 書中的框（Case History 之類），從框標題到下一個標題，或到正文以小寫字母接續為止 | 和正文分開，避免框的內容混進觀念說明 |

所有 Markdown 依檔名自然排序當成一條連續的文字流，跨檔的例題不會被切斷。
例題「不要」照固定長度切：題目和解答分開就失去意義。長度問題留給第 5 段的片段切分處理。

## 執行
```bash
python3 $S/chunk_markdown.py markdown --profile book_profile.json \
    --hints layout_hints.json --out chunks.jsonl
python3 $S/validate_chunks.py chunks.jsonl --profile book_profile.json \
    --expect-sections 1.1,1.2,...      # 可省略；有目錄時建議帶上
```
切塊器的輸出要逐行讀：章節數、目錄解析到幾節、幾節靠目錄標題辨認、
幾處靠題號字型辨認出習題、哪些「像章節標題但順序不合理」的行被當成內文，
以及章導論數、側欄數、接回的斷句數。輸出若列出「可能是側欄的全大寫標題」，
打開那幾處看是不是書中的框：是的話把它們寫進 `sidebar_heading`（只寫看到的框名，
不要寫成「所有全大寫」，因為 SOLUTION、FIGURE 3、PROOF 也是全大寫），並在 evidence 記下位置。

## OCR 讓標題變形的方式，與切塊器的對策
實際在 Stewart 微積分看到的，其他書大多也會發生：

| 現象 | 例子 | 對策 |
|---|---|---|
| 交叉引用看起來像標題 | 附錄裡的 `Section 2.4`、本文的 `## 6.3 Exercises` | 章節編號只能「合理地往前」：同章最多跳 3 節，或進入下兩章 |
| 章節編號被漏掉 | 1.5 節只剩 `## The Limit of a Function` | 解析目錄頁；標題等於「接下來 2 節」之一時開新節（Stewart 有 33 節靠這個找回） |
| 編號和標題分成兩行 | `## 1.1` 下一行 `## Four Ways to Represent a Function` | 下一個標題行當作章節名稱 |
| 目錄跨兩個檔案 | 第二個檔案沒有 `## Contents` | 有 10 行以上目錄格式的檔案也視為目錄 |
| 小節名稱和後面某節同名 | 6.3 裡的小標題「The Natural Logarithmic Function」= 6.2\* 的節名 | 用目錄標題比對時，不能跳過本文中有編號的節 |
| 帶 \* 的替代章節 | 6.2\*～6.4\* 印在 6.4 之後 | 依目錄順序；沒有目錄時，帶 \* 的節可在同章內往回 |
| 「Exercises」標籤不見 | 習題頁被移除，殘留的題目接在例題後 | 用字型提示的題號＋開頭文字比對（Stewart 88 處） |
| 附錄 | `## Appendixes` 後是 A～H，節名只在目錄出現 | `appendix_start` 之後改用附錄目錄比對，`part` 標為 `appendix` |
| 章概述沒有章節編號 | `# Computer Networks and the Internet` 後面 4 段，才到 `## 1.1` | `chapter_heading`（預設：單一個 `#`）開始一塊 `chapter_intro`，遇到第一節時補上章號 |
| 框（側欄）插在句子中間 | `…an e-mail` ／ `## CASE HISTORY` 框內容 ／ `client program, …` | 設定 `sidebar_heading`：框獨立成一塊，小寫開頭的接續段落放回被打斷的那一塊（公式區塊內不判斷） |
| 一句話被分頁切成兩段 | `…so the` ／ `ISPs that provide…` | `join_broken_paragraphs`：下一段小寫開頭，或上一段停在冠詞或介系詞時才接回。只看「沒有句號」不夠，數學書常在講到一半時插入公式 |
| 目錄的頁碼或型號被當成章節 | `Wireshark Lab: 802.11 … 557` | 預設 `toc_entry` 的編號每層最多 2 位數 |

## 調設定檔的循環
1. 用預設值跑一次，看輸出摘要與 `validate_chunks.py`。
2. 對每個問題，找出具體的檔案和行號（`source_spans` 有記），讀那幾行判斷原因。
3. 改 `book_profile.json` 的對應 pattern，在 `evidence` 寫下原因。
4. 重跑，和上一次比較：章節集合、每節例題數、哪些塊變了。改善一處卻弄壞另一處很常見
   （實例：為了排除小標題誤判成章節，結果把章節本身的標題也排除了，少了 2.5 和 15.8）。
   每次改動都要比較整體數字，不能只看想修的那一處。

比較兩次切塊結果的小腳本：
```python
import json, collections as C
a = [json.loads(l) for l in open("chunks.old.jsonl")]
b = [json.loads(l) for l in open("chunks.jsonl")]
key = lambda r: (r["part"], r["section"])
print("只在舊版:", sorted({key(r) for r in a} - {key(r) for r in b}))
print("只在新版:", sorted({key(r) for r in b} - {key(r) for r in a}))
ea, eb = (C.Counter(key(r) for r in x if r["kind"] == "example") for x in (a, b))
print("例題數不同的節:", [(s, ea[s], eb[s]) for s in sorted(set(ea) | set(eb)) if ea[s] != eb[s]])
```

## 驗收
- 章節數等於目錄的章節數（附錄另計）。
- `validate_chunks.py` 沒有 FAIL；每個 WARN 都看過並在報告裡解釋
  （例如「重複內容：6.4 與 6.2\* 課本本來就印了同一段」是可接受的）。
- 例題有解答標記的比例：Stewart 是 86%，沒有的多半是題目只有一行就直接解。低於 80% 要查。
- 抽查 3 個例題的開頭和結尾，對照 PDF。

## 實測基準（Stewart 微積分 195 份）
通用腳本＋`assets/book_profile.stewart-calculus.json`：本文 120 節、附錄 6 節，
和專案手寫的 618 行專用版本章節集合完全一致；例題 889 題，只有 7.2 節少 1 題；
721 題的內容逐字相同，其餘差在例題結尾的位置。換新書時，可用這組數字當作
「通用腳本做得到的程度」的參考。

## 什麼時候該改程式而不是調設定
通用切塊器涵蓋「章節／小標題／例題／習題／附錄」這種結構。書的結構差很多時
（例如定義與定理要獨立成塊、例題沒有 EXAMPLE 字樣只有編號、雙欄排版造成段落交錯），
把 `scripts/chunk_markdown.py` 複製到專案裡改，保持輸出欄位不變
（`index, id, kind, part, section, section_title, label, text, source_files, source_spans`），
後面的腳本就都能用。改完一樣用 validate 與比較腳本驗證。
