# 测试知识库

LangGraph Agent 当前已经支持本地 RAG 知识库。
知识库使用 Chroma 保存向量索引，使用 chunks.jsonl 保存 chunk metadata。
RAG 支持 /rag add、/rag list、/rag sync 和 /rag rebuild。
RAG 还支持 /rag delete 和 /rag clear。