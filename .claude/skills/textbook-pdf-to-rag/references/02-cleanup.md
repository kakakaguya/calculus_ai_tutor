# 2 清理 OCR 的系統性錯誤

目標是修「整本書反覆出現的同一種錯」，不是逐字校對。單一檔案的偶發錯誤，
由使用者手動改，然後列進 `protected_files`。

## 內建的通用規則（每本書都會套用）
| 規則 | 修什麼 | 為什麼不會誤傷 |
|---|---|---|
| 圖片 | base64 圖片 → `<!-- image -->` | 圖片對檢索沒用，而且會塞爆文字塊 |
| 空表格→圖 | 至少 20 格且 90% 以上是空的表格 → 佔位 | 有格線的圖表被讀成大表格；真表格不會幾乎全空 |
| `\|array\|` 外框 | `\left\| \begin{array} … \right\|` 且每一列都有 `=`、`<` 等關係 → 拿掉外框 | 真的行列式每列沒有關係符號，不會被拆 |
| 空行 | 連續 3 行以上的空行 → 1 個空行 | — |

## 找出這本書特有的錯誤
1. 抽樣：挑 3 至 5 份不同章節的 Markdown，對照 PDF 讀一遍。
2. 找重複出現的東西，用 grep 計數確認它真的是系統性的：
   ```bash
   grep -c "Copyright" markdown/*.md | awk -F: '$2>0' | wc -l     # 幾個檔案有頁尾
   grep -o '\\varliminf' markdown/*.md | wc -l                       # 可疑的巨集
   grep -h '^#' markdown/*.md | sort | uniq -c | sort -rn | head -30 # 反覆出現的「標題」=頁眉頁尾
   ```
3. 每發現一種，寫進設定檔，並在 `evidence` 記下範例位置與次數。

常見的書本特有錯誤：出版社頁尾或頁眉（整行刪）、OCR 誤讀的 LaTeX 巨集
（例如 MinerU 把 `\lim` 讀成 `\varliminf`）、章節名重複印在每頁頁眉。

## 規則怎麼寫
- `delete_line_patterns`：匹配到的「整行」會刪掉。只放確定整行都是雜訊的特徵字串。
- `replacements`：`[正規表示式, 取代字串]`。用 `(?![A-Za-z])` 這類邊界，避免改到更長的巨集名。
- 規則必須冪等（idempotent）：套用兩次和一次結果相同。驗收時再跑一次 `--dry-run`，
  應該顯示「會修改 0 個檔案」。

## 執行
```bash
python3 $S/clean_markdown.py markdown --profile book_profile.json --dry-run
python3 $S/clean_markdown.py markdown --profile book_profile.json --backup backup
python3 $S/clean_markdown.py markdown --profile book_profile.json --dry-run   # 應為 0
```
看 dry-run 每條規則的觸發次數：某條規則次數遠超出預期（例如頁尾規則刪了 5000 行，
但書只有 1200 頁），代表它匹配到不該刪的內容，先修規則再正式跑。
受保護的檔案會顯示「會觸發哪些規則」但不會被改，必要時請使用者手動套用。

## 還原
備份在 `backup/markdown_before_cleanup.tar.gz`，只在第一次正式寫入時建立。
清理規則改錯時：解開備份覆蓋 `markdown/`（受保護檔除外），修好規則再跑。
