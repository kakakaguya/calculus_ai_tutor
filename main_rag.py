
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

model = ChatOllama(model ="qwen3:8b")


messages=[

    SystemMessage(
         content = "你是一位專業的微積分助教，使用繁體中文簡潔回答。"
    ),

    HumanMessage(
        content = "請幫我解釋一下微積分中的極限概念，並舉一個簡單的例子來說明。"
    )
]

res = model.stream(input = messages)


for chunk in res:
    print(chunk.content, end="", flush=True)