# Pipeline de Integração: Bagy XML -> OpenAI Commerce Feed

Este projeto converte e trata o feed XML da loja Bagy / Dooca (`30.005 produtos`) para o padrão oficial exigido pela especificação do **OpenAI Agentic Commerce (Product File Upload)**.

Documentação Oficial OpenAI: [https://developers.openai.com/commerce/specs/file-upload/products](https://developers.openai.com/commerce/specs/file-upload/products)

---

## 🚀 Como Executar

### 1. Teste Rápido (50 itens)
```bash
python convert_feed.py --test
```

### 2. Execução Completa (30.005 itens)
Processa todo o feed de 63 MB em cerca de **6 segundos**:
```bash
python convert_feed.py
```

Arquivos gerados na pasta:
- `openai_products_feed.csv`: Tabela tratada pronta para importar no Google Sheets ou carregar na OpenAI.
- `openai_products_feed.jsonl`: Formato nativo JSONL da OpenAI com objetos de variantes (`variant_dict`) aninhados.

---

## 📊 Como colocar no Google Sheets

### Método 1: Importação Direta (Mais simples)
1. Abra uma nova planilha no [Google Sheets](https://sheets.new).
2. Clique em **Arquivo > Importar > Fazer upload**.
3. Selecione o arquivo `openai_products_feed.csv`.
4. Escolha **Substituir planilha atual** e clique em **Importar dados**.

### Método 2: Sincronização Automática via API
Se quiser que o script atualize a planilha automaticamente:
1. Instale o gspread: `pip install gspread`
2. Crie uma Service Account no Google Cloud Console e baixe o arquivo de credenciais como `service_account.json`.
3. Compartilhe sua planilha do Google Sheets com o e-mail da Service Account (com permissão de Editor).
4. Execute passando o ID da planilha:
```bash
python convert_feed.py --sheets-id "SEU_SPREADSHEET_ID_AQUI"
```

---

## 🤖 Automação 100% Gratuita (GitHub Actions)
Já deixamos configurado em `.github/workflows/update_feed.yml` um fluxo de automação:
- Roda todo dia às 00:00 (Brasília).
- Baixa o feed da Bagy, trata e salva os arquivos `.csv` e `.jsonl` atualizados no repositório.
- Não precisa de servidor nem do seu computador ligado.
