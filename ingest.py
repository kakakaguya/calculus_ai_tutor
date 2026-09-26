from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    EasyOcrOptions,      # 或改用 TesseractCliOcrOptions / RapidOcrOptions
)
from docling.datamodel.pipeline_options import TesseractCliOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from langchain_docling import DoclingLoader
from langchain_docling.loader import ExportType
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pathlib import Path
from pypdf import PdfReader

file_path = Path(
    "~/workspace/學習課程助教系統/rag/data/Thomas_Calculus.pdf"
).expanduser()

pipeline_options = PdfPipelineOptions(
    do_ocr=True,
    do_table_structure=True,
    do_formula_enrichment=True,
)


pipeline_options.ocr_options = EasyOcrOptions()  # 或改用 TesseractCliOcrOptions / RapidOcrOptions
# 關鍵：強制整頁走 OCR，不要信任內嵌文字層
pipeline_options.ocr_options.force_full_page_ocr = True


# 拉高解析度再做 OCR，對細小的上標/符號辨識率影響很大
pipeline_options.images_scale = 2.0  # 預設通常是 1.0，數學符號建議 2.0~3.0
pipeline_options.generate_page_images = True

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=pipeline_options
        )
    }
)

loader = DoclingLoader(
    file_path=str(file_path),
    export_type=ExportType.MARKDOWN,
    converter=converter,
)

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=150,
)

embedding = OllamaEmbeddings(model = "nomic-embed-text")

vectorstore = Chroma(
    collection_name="calculus",
    embedding_function=embedding,
    persist_directory="./chroma_db"
)
reader = PdfReader(str(file_path))
total_pages = len(reader.pages)

document = loader.load()

print(f"Documents: {len(document)}")

for i in range(len(document)):
    print(f"\n========== Document {i + 1} ==========")
    print(document[i].page_content[:10000])
    print("\nMetadata:")
    print(document[i].metadata)



print(f"總頁數: {total_pages}")
print(f"總字數: {len(document[0].page_content)}")
print("解析完成，開始切割文本...")

chunks = text_splitter.split_documents(document)

print(f"切割完成，總共 {len(chunks)} 個文本塊。")

print("開始將文本塊加入向量資料庫...")

vectorstore.add_documents(chunks)



print("\n讀取完成！")