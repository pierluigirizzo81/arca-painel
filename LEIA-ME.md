# Painel ARCA — publicação gratuita (caminho 1)

O painel fica público na internet, mas **não contém nenhum dado seu**.
Seus saldos ficam só no navegador, depois que você importa a planilha Excel.

## Passo a passo

1. Crie uma conta gratuita em https://github.com.
2. Crie um repositório **público** (ex.: `arca-painel`), sem README.
3. Envie o conteúdo desta pasta: na página do repositório, clique em
   **uploading an existing file** e arraste `docs`, `scripts`, `.github`,
   `requirements.txt` e `.gitignore`. (Se a pasta `.github` não subir pelo
   navegador, use **Add file > Create new file** e digite o caminho
   `.github/workflows/cotacoes.yml`, colando o conteúdo do arquivo.)
4. Em **Settings > Pages**: Source = *Deploy from a branch*,
   Branch = `main`, pasta = `/docs`. Salve.
5. Em **Actions**, abra *Atualizar cotações* e clique em **Run workflow**
   (na primeira vez, aceite habilitar os workflows).
6. Depois de 1 a 2 minutos, abra `https://SEU-USUARIO.github.io/arca-painel/`.
7. No painel: aba **Importação**, selecione a planilha `ARCA SINTESE.xlsx`,
   confira a prévia e confirme.

## Regras de ouro

- **Nunca** envie a planilha Excel, CSVs ou prints da carteira ao repositório.
- Os dados ficam no navegador de cada dispositivo. No celular, importe a planilha de novo.
- Para acompanhar outros ETFs, inclua o ticker em `scripts/cotacoes.py`
  (lista `TICKERS`) e no radar do painel, com a fonte "yahoo".

## Lista de ativos (radar.txt)

Edite `radar.txt` (direto no GitHub, com o lápis) para escolher os ativos.
Formato: `tipo;ticker;nome`, com tipo `acao`, `fii`, `etf_eua` ou `etf_irlanda`.
Ao salvar, as cotações são atualizadas automaticamente em cerca de 1 minuto.
O P/VP vem do Fundamentus (só ações e FIIs) e pode ficar vazio quando indisponível.

## Tesouro Direto

O script baixa o arquivo público de preços e taxas do Tesouro Transparente e mostra
Prefixados, IPCA+ e RendA+ 2065 na aba Mercado (taxas e preços de abertura do último dia disponível).
