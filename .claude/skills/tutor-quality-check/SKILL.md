---
name: tutor-quality-check
description: 檢查微積分助教系統（rag/ 專案：Ollama qwen3 + nomic-embed-text + Chroma）的檢索與回答品質，並判斷錯誤出在檢索還是模型。只要使用者說助教答錯了、找錯章節、回答有簡體字或怪怪的、想知道改了提示詞／切塊／檢索／embedding 模型之後有沒有變好或變差、要做回歸測試或比較版本，或要新增容易答錯的測試題，就使用這個 skill，即使沒說「測試」。不適用：重新切課本（用 textbook-pdf-to-rag）、修網頁介面或資料庫等一般程式工作。
---

# 助教系統品質檢查

助教回答學生的流程是：中文問題 → qwen3 翻成英文檢索詞 → nomic 比對 section_text 片段 →
取回完整子主題 → qwen3 依教材回答並附章節來源。答錯時，錯誤可能出在任何一步，
所以先量、再定位、最後才改。

檔案（路徑相對於 `rag/`）：
- `.claude/skills/tutor-quality-check/questions.jsonl`：測試題庫，每題有期望章節、類別、
  必須包含的重點（key_points）和已知陷阱（pitfall）
- `scripts/check_retrieval.py`：只檢查檢索（快，約 1 秒一題）
- `scripts/check_answers.py`：讓助教真的回答（慢，約 40–60 秒一題）並做自動檢查
- 結果寫在 `data/quality_runs/`（不進 git），檔名帶時間，下一次會自動拿來比較

一律在 `rag/` 用專案的虛擬環境執行：`.venv/bin/python .claude/skills/tutor-quality-check/scripts/…`。
需要 Ollama 執行中、向量資料庫已建好；失敗時腳本會說缺什麼，照指示做（建庫用
`python -m ingestion.build_vector_db`）。

## 1. 先量檢索（每次都做）

```bash
.venv/bin/python .claude/skills/tutor-quality-check/scripts/check_retrieval.py --note "改了什麼"
```
每題標示 ✓1（第一名就是期望章節）、✓（前幾名有）、✗（沒有）、·（教材外，不評分），
並列出 qwen3 翻出的檢索詞。結尾會和上一次的結果比較，列出改善與變差的題目。
改動前先跑一次當基準，改完再跑一次；只要有任何一題「變差」，就要說明原因，
不能只報總分。

題目類別：
- `control`：一般觀念題，應該全對。錯了代表系統壞了，先查環境與資料
- `terminology`：台灣用語、符號、簡體字等容易在翻譯或比對時跑掉的問法
- `trap`：檢索對了模型也可能答錯的題目（數學陷阱）
- `out_of_scope`：課本沒有的內容

## 2. 定位錯誤出在哪一步

對每一題 ✗，依序檢查，找到第一個出錯的地方就停：

| 檢查 | 怎麼看 | 常見原因與處理 |
|---|---|---|
| 翻譯 | 結果裡的「檢索詞」 | 漏掉關鍵詞（「微分」被吃掉）、**自己加了解法**（自動加上 "using L'Hospital's Rule"）、加了書名。修改 `tutor/query_rewrite.py` 的提示詞：只翻譯原文，不加方法、定理或書名；台灣譯名寫進對照（洛必達、羅必達 → L'Hospital） |
| 教材裡有沒有 | `data/chunk_tree.jsonl` 找該節 | 期望章節不存在或內容被切錯 → 交給 textbook-pdf-to-rag 處理 |
| 比對 | 用英文直接問同一題（`python -m tutor.main_rag "English question" --show-context`） | 英文對、中文錯 → 跨語言問題（nomic 只懂英文）；英文也錯 → 用語和課本不同（「0 除以 0」vs. indeterminate form），在翻譯對照補課本用語，或考慮多語言模型 |
| 排名 | 期望章節在第 2–3 名 | 相近主題搶第一（黎曼和 → 15.1 二重積分）。通常可接受；若要改善，考慮加上重新排序 |

改了任何一處，回到步驟 1 重跑整套，確認其他題沒有變差。

## 3. 檢查回答（檢索對了，回答仍可能錯）

```bash
.venv/bin/python .claude/skills/tutor-quality-check/scripts/check_answers.py --only trap,out_of_scope
```
這一步慢，預設只跑陷阱題和教材外題目；要跑指定題目就用 `--only` 加上 id。

腳本自動檢查程式能判斷的部分：簡體字、有沒有附來源、引用編號［n］是否對應得到來源、
LaTeX 符號是否成對。**數學對不對由你判斷**：打開產生的 `…-answers.md`，逐題拿回答
對照 `key_points` 和 `pitfall`。不要叫 qwen3 自己評分，它就是被測的對象，
而且這些陷阱題它自己就答錯過。

判斷時特別注意：
- 陷阱題的結論（1/x 從 −1 積到 1 是**發散**，不是 0；∫1/x dx 要有**絕對值**）
- 用詞精確（sin θ < θ 證明裡的 θ 是**弧長**，不是弦長）
- 證明方法有沒有循環論證（用羅必達證明 sin x/x → 1）
- 教材外的題目，回答有沒有說「教材沒有」，還是硬引用不相關的章節
- 簡體字（例如「几何」）

回答錯但檢索正確時，出錯的是模型這一步：看 `tutor/main_rag.py` 的 `SYSTEM_PROMPT`、
`NUM_CTX`（太小時教材會被截掉，回答會像沒看到教材），或模型的思考模式。

## 4. 新增測試題

使用者或你發現新的錯誤時，把它加進 `questions.jsonl`，讓之後每次都會測到：
```json
{"id": "trap-短名稱", "question": "學生的原話", "category": "trap",
 "expect_sections": ["7.8"], "key_points": ["正確答案必須包含的事"], "pitfall": "曾經怎麼錯"}
```
期望章節要先在 `data/chunk_tree.jsonl` 確認存在。教材外的題目用 `"expect_sections": []`。

## 5. 回報格式

```markdown
## 檢索：命中 21/23（第一名 17）｜與上次比較：改善 2、變差 0
| 題目 | 期望 | 實際 | 判斷 |
|---|---|---|---|
| 微分和導數有什麼不同？ | 2.9 | 1.8, 2.2 | 翻譯漏掉「微分」→ 已修提示詞 |
## 回答：自動檢查 5/6 通過；數學判斷
| 題目 | 結論 | 問題 |
|---|---|---|
| 1/x 從 -1 積到 1 | ✗ | 答 0，沒發現瑕點 |
## 建議下一步
```
每一題的判斷都要說清楚是「檢索」還是「模型」的問題；還沒確認的寫「未確認」。
