import streamlit as st
import requests

# URL base do seu FastAPI
API_URL = "http://localhost:8000"

# ==========================================
# CONFIGURAÇÃO E ESTILO DA PÁGINA
# ==========================================
st.set_page_config(page_title="Assistente IA", page_icon="🧠", layout="wide")

# CSS para esconder menus do Streamlit e deixar mais limpo
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container {padding-top: 2rem;}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# VARIÁVEIS DE ESTADO
# ==========================================
if "thread_id" not in st.session_state:
    st.session_state.thread_id = st.query_params.get("chat")
    
if "messages" not in st.session_state:
    st.session_state.messages = []

# ==========================================
# RESGATE AUTOMÁTICO DE HISTÓRICO
# ==========================================
if st.session_state.thread_id and not st.session_state.messages:
    try:
        historico_response = requests.get(f"{API_URL}/ai/{st.session_state.thread_id}/history")
        if historico_response.status_code == 200:
            st.session_state.messages = historico_response.json().get("messages", [])
    except:
        pass 

# ==========================================
# BARRA LATERAL (Sidebar)
# ==========================================
with st.sidebar:
    st.title("🧠 Assitente Local")
    st.caption("Seu cérebro digital e autônomo.")
    
    if st.button("➕ Nova Conversa", use_container_width=True, type="primary"):
        response = requests.post(f"{API_URL}/chats/", json={"title": "Nova Conversa"})
        if response.status_code == 201:
            data = response.json()
            st.session_state.thread_id = data["thread_id"]
            st.query_params["chat"] = data["thread_id"]
            st.session_state.messages = []
            st.rerun()

    st.divider()
    st.markdown("### Histórico")

    try:
        response_chats = requests.get(f"{API_URL}/chats/")
        if response_chats.status_code == 200:
            chats = response_chats.json()
            
            for chat in chats:
                col1, col2 = st.columns([4, 1])
                
                # 📌 UI TWEAK: Deixa o botão azul se for o chat atual
                is_active = st.session_state.thread_id == chat['thread_id']
                button_type = "primary" if is_active else "secondary"
                
                with col1:
                    if st.button(f"💬 {chat['title'][:20]}", key=f"chat_{chat['id']}", use_container_width=True, type=button_type):
                        st.session_state.thread_id = chat['thread_id']
                        st.query_params["chat"] = chat['thread_id']
                        st.session_state.messages = [] 
                        
                        historico_url = f"{API_URL}/ai/{chat['thread_id']}/history"
                        historico_response = requests.get(historico_url)
                        if historico_response.status_code == 200:
                            data = historico_response.json()
                            for msg in data.get("messages", []):
                                st.session_state.messages.append(msg)
                        st.rerun()
                
                with col2:
                    if st.button("🗑️", key=f"del_{chat['id']}", help="Apagar"):
                        del_response = requests.delete(f"{API_URL}/chats/{chat['id']}")
                        if del_response.status_code == 204:
                            if st.session_state.thread_id == chat['thread_id']:
                                st.session_state.thread_id = None
                                st.query_params.clear() 
                                st.session_state.messages = []
                            st.rerun()
                            
    except requests.exceptions.ConnectionError:
        st.error("🔌 Servidor FastAPI offline.")

# ==========================================
# TELA CENTRAL (O Chat)
# ==========================================

if not st.session_state.thread_id:
    # 📌 UI TWEAK: Tela inicial bonita
    st.markdown("<h1 style='text-align: center; color: #4F8BF9;'>Bem-vindo ao seu Assistente IA</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; font-size: 1.2rem;'>Escolha um chat na barra lateral ou inicie uma nova conversa para começar.</p>", unsafe_allow_html=True)
    st.divider()
    
    col1, col2, col3 = st.columns(3)
    col1.info("💡 **Dica:** Use `@heavy` para forçar o DeepSeek 70B em perguntas complexas.")
    col2.info("📝 **Código:** Peça funções em Python, SQL ou scripts de automação.")
    col3.info("🚀 **Fila (Batch):** Envie múltiplas tarefas para rodar em background.")

else:
    # PAINEL DE PROCESSAMENTO EM LOTE (BACKGROUND)
    with st.expander("⚙️ **Usina de Tarefas (Processamento em Lote / Celery)**"):
        st.markdown("Deixe tarefas pesadas rodando no background. Pule uma **linha vazia (Enter duplo)** para separar as tarefas.")
        
        batch_input = st.text_area(
            "Lista de Tarefas:", 
            height=150, 
            placeholder="@heavy Analise a arquitetura X...\n\nCrie um guia completo sobre Y..."
        )
        
        if st.button("🚀 Enviar para a Fila", type="primary"):
            prompts = [p.strip() for p in batch_input.split('\n\n') if p.strip()]
            
            if not prompts:
                st.warning("⚠️ Insira pelo menos uma tarefa.")
            else:
                with st.spinner(f"Enfileirando {len(prompts)} tarefa(s)..."):
                    try:
                        batch_response = requests.post(f"{API_URL}/ai/batch/", json={"thread_id": st.session_state.thread_id, "prompts": prompts})
                        if batch_response.status_code == 200:
                            st.success(f"✅ {len(prompts)} tarefa(s) enviada(s)! Pode ir fazer outras coisas.")
                        else:
                            st.error("Erro no servidor.")
                    except Exception as e:
                        st.error(f"Erro de conexão: {e}")

    # ==========================================
    # RENDERIZAÇÃO DAS MENSAGENS ANTIGAS
    # ==========================================
    for msg in st.session_state.messages:
        # Avatares diferenciados!
        avatar = "🧑‍💻" if msg["role"] == "user" else "🤖"
        
        with st.chat_message(msg["role"], avatar=avatar):
            if msg["role"] == "assistant" and msg.get("model"):
                st.caption(f"🧠 *{msg['model']}*")
            st.markdown(msg["content"])
            
            if msg["role"] == "assistant":
                with st.expander("📋 Ver formato puro"):
                    st.code(msg["content"], language="markdown")

    # ==========================================
    # NOVO CHAT COM STREAMING (LETRA POR LETRA)
    # ==========================================
   # 2. Caixa de input para o usuário (Tempo Real)
    if user_input := st.chat_input("Digite sua mensagem para a IA..."):
        
        with st.chat_message("user"):
            st.markdown(user_input)
            with st.expander("📋 Copiar texto puro"):
                st.code(user_input, language="markdown")
            
        st.session_state.messages.append({"role": "user", "content": user_input})

        with st.chat_message("assistant"):
            st.caption("🧠 *IA Processando...*")
            
            def ler_stream_da_api():
                payload = {
                    "thread_id": st.session_state.thread_id,
                    "message": user_input
                }
                try:
                    # chunk_size=1024 ajuda a manter as quebras de linha mais estáveis
                    resposta = requests.post(f"{API_URL}/ai/", json=payload, stream=True)
                    
                    if resposta.status_code != 200:
                        yield f"Erro no servidor: {resposta.status_code}"
                        return
                        
                    for chunk in resposta.iter_content(chunk_size=1024, decode_unicode=True):
                        if chunk:
                            yield chunk
                except Exception as e:
                    yield f"Erro de conexão: {e}"

            # Escreve suavemente na tela
            texto_completo = st.write_stream(ler_stream_da_api)

        # ==========================================
        # 📌 O TRUQUE MÁGICO: RESGATE DO MODELO E FORMATAÇÃO
        # ==========================================
        # Quando a IA termina de digitar, o LangGraph já salvou no banco de dados.
        # Vamos buscar o nome do modelo real que o Roteador escolheu!
        modelo_real = "IA Local"
        try:
            historico_url = f"{API_URL}/ai/{st.session_state.thread_id}/history"
            hist_req = requests.get(historico_url)
            if hist_req.status_code == 200:
                mensagens_banco = hist_req.json().get("messages", [])
                if mensagens_banco:
                    # Pega o modelo exato da última mensagem salva
                    modelo_real = mensagens_banco[-1].get("model", "IA Local")
        except:
            pass

        # Salva na sessão com o nome real do modelo
        st.session_state.messages.append({
            "role": "assistant", 
            "content": texto_completo, 
            "model": modelo_real 
        })
        
        # O st.rerun() redesenha a tela inteira em milissegundos.
        # Isso revela o nome do modelo (Ex: Qwen 30B) e aplica o Markdown perfeito no código!
        st.rerun()