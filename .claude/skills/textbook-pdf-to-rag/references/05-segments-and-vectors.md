# 5 父子結構、embedding 片段與向量庫

## 父子結構：比對用小片段，回答用完整內容
```text
3.4 Limits at Infinity
├── ■ Limits at Infinity and Horizontal Asymptotes   section_text（父）
│   ├── Example 1                                    example（子，parent_id 指向父）
│   └── Example 2
└── ■ Evaluating Limits at Infinity
    └── Example 3 …
```
切塊器在每個小標題開新的 section_text，所以「例題前面最近的那塊 section_text（同一節）」
就是它應用的觀念。Stewart 890 個例題全部能這樣掛上去。

```bash
python3 $S/build_segments.py chunks.jsonl --tree chunk_tree.jsonl --segments segments.jsonl
```
- `chunk_tree.jsonl`：每塊完整內容＋`parent_id`、`child_ids`、`subheading`、`segment_ids`。回答時用。
- `segments.jsonl`：只有要做 embedding 的種類，超過上限才切。檢索時用，每片用 `chunk_id` 指回完整塊。

## 哪些要做 embedding（`--embed-kinds`）
預設是 `section_text` 和 `sidebar`（章導論也屬於 section_text）：回答根據教材觀念，例題透過 `child_ids` 需要時再帶出。
代價是「這題怎麼算」這類解題型問題，和例題的相似度通常比和觀念說明高，可能漏掉。
這是使用者要做的取捨，說明後讓他們選；做比較實驗時可加 `example`。
習題（`exercises`）沒有解答，一般不要做 embedding。

## 片段大小
- 上限 500 token、下限 100 token（小於下限的片段併入相鄰片段）。
- 只在段落邊界切；`$$` 公式和前面的引導句、後面以小寫或標點開頭的「where …」綁在一起；
  標題和下面的段落綁在一起。單一段落太長才用句點切，而且不在 `$…$` 裡切。
- 每片前面加標頭 `3.4 Limits at Infinity | Evaluating Limits` 再算 embedding，
  讓短片段也帶著章節脈絡（contextual header）。不需要固定字元數的 overlap。
- token 用「字元數 ÷ 每 token 字元數」估算。nomic-embed-text 在 LaTeX 很多的英文教材上
  實測是 3.35；**換 embedding 模型要重新量**：
  ```python
  # 用 Ollama 回傳的 prompt_eval_count 量實際 token 數
  import json, urllib.request
  def count(text, model="nomic-embed-text"):
      body = json.dumps({"model": model, "input": text}).encode()
      req = urllib.request.Request("http://127.0.0.1:11434/api/embed", data=body,
                                   headers={"Content-Type": "application/json"})
      return json.load(urllib.request.urlopen(req))["prompt_eval_count"]
  # 對 50 個片段算 len(text)/count(text) 的平均，傳給 --chars-per-token
  ```
- nomic-embed-text 的 context 是 2048 token，超過的部分會被截掉，只有前半段進向量。
  `build_segments.py` 會回報超過上限的片段數，應為 0。

## 向量庫
```bash
python3 $S/build_vector_db.py segments.jsonl --persist database/chroma_db \
    --collection textbook_sections
```
- 每次重建整個 collection，以片段 id 當 Chroma id：重跑不會留下重複的兩份。
- nomic-embed-text 必須加任務前綴：文件 `search_document: `（腳本已加），
  **查詢端要加 `search_query: `**，不加 recall 會明顯下降。collection 的 metadata 記錄了這件事。
- 建完用 3 個英文查詢測試，看是否命中對的章節（例如 chain rule → 2.5）。

## 檢索端要注意的事（交給寫 RAG 程式的人）
- **跨語言**：教材英文、學生用中文問時，nomic-embed-text 只懂英文，會找錯章節
  （實測「連鎖律怎麼用」命中 8.4 經濟學應用）。解法：檢索前用 LLM 把問題翻成英文檢索詞，
  或改用多語言 embedding（如 bge-m3）。翻譯提示要求「只翻譯，不要加入解題方法」，
  否則模型會自行加上「using L'Hospital's Rule」把檢索帶偏。
- 命中片段後用 `chunk_id` 取完整塊，再依需要用 `child_ids` 取例題；控制總長度。
- Ollama 的聊天模型預設 context 窗口較小，送入多塊教材時要設定 `num_ctx`（例如 8192），
  否則教材會被悄悄截掉。
- 回答附來源時用 `section`＋`section_title`（例如「7.1 Integration by Parts」），同節合併。

## 交接給團隊
- `data/` 常被 `.gitignore` 排除。隊友要建向量庫，至少需要 `segments.jsonl`；
  執行檢索還需要 `chunk_tree.jsonl`。要進 git 就用 `git add -f`，並提醒之後重切要一起更新。
- Chroma 資料夾是二進位 SQLite，不要進 git；每個人本機重建（約 15～30 秒）。
