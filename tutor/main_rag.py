from pathlib import Path
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHROMA_DB_DIR = PROJECT_ROOT / "database" / "chroma_db"


llm = ChatOllama(model="qwen3:8b", temperature=0.1) 
embeddings = OllamaEmbeddings(model="nomic-embed-text")

#連到Chroma向量資料庫跟設定檢索器
vectorstore = Chroma(
    persist_directory=str(CHROMA_DB_DIR),
    embedding_function=embeddings
)
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

system_prompt = (
    "你是一位專業的微積分助教，請使用繁體中文簡潔回答。\n"
    "請務必「優先」使用以下提供的參考資料來回答問題。\n"
    "如果參考資料中無法回答該問題，請依靠你的專業知識補充，但要說明哪些部分來自教材。\n\n"
    "【參考資料】\n{context}"
)

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{input}")
])

#自訂函數：把資料庫找出來的 3 段課本內容，融合成一段大字串
def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

#建立 LCEL 檢索鏈
rag_chain = (
    {"context": retriever | format_docs, "input": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)

def get_answer_stream(question: str):
    """
    接收問題，從資料庫檢索課文後，串流輸出 AI 的回答。
    """
    print(f"\n 問題：{question}")
    print(" 助教回答：", end="", flush=True)
    
    # 執行 RAG 串流
    for chunk in rag_chain.stream(question):
        print(chunk, end="", flush=True)
    print("\n" + "-"*50)

if __name__ == "__main__":
    # 測試一下 RAG 是否有讀到微積分教材
    get_answer_stream("請幫我解釋一下微積分中的極限概念，並舉一個簡單的例子來說明。")