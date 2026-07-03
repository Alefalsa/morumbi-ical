# Agenda iCal do MorumBIS (jogos + eventos)

Gera automaticamente um arquivo `.ics` com:
- **Jogos do São Paulo FC no MorumBIS** — extraídos da agenda oficial do clube
  (`saopaulofc.net/calendario-de-jogos`). Bem confiável: é a fonte oficial,
  estruturada, com data, horário e local de cada partida.
- **Shows/eventos não-futebolísticos** — extraídos das notícias da categoria
  "Eventos" do site oficial (`saopaulofc.net/categoria/eventos`). **Menos
  confiável**, porque o clube não publica uma agenda futura estruturada de
  shows — só notícias em texto livre. Esses eventos entram no calendário
  marcados como `TENTATIVE` (provisórios), com 🎤❓ no título e link da
  notícia-fonte na descrição, para você confirmar manualmente.

Um GitHub Actions roda isso todo dia e commita o `.ics` atualizado no
repositório, então você assina a URL do arquivo no Google Calendar / Apple
Calendar / Outlook e ele atualiza sozinho.

---

## 1. Subir este projeto para um repositório seu no GitHub

```bash
cd morumbi-ical
git init
git add .
git commit -m "Setup inicial"
gh repo create morumbi-ical --public --source=. --push
# (ou crie o repo manualmente no github.com e faça git remote add origin ... && git push)
```

## 2. Habilitar permissão de escrita para o Actions

No repositório no GitHub: **Settings → Actions → General → Workflow
permissions** → selecione **"Read and write permissions"** → Save.

(Sem isso, o passo `git push` do workflow falha com erro 403.)

## 3. Rodar uma vez manualmente para gerar o primeiro `morumbis.ics`

Na aba **Actions** do repositório → workflow **"Atualizar agenda do
MorumBIS"** → **Run workflow**. Depois disso ele roda automaticamente todo
dia (veja o `cron` em `.github/workflows/update-ics.yml` se quiser mudar o
horário/frequência).

## 4. Assinar o calendário

A URL pública e sempre atualizada do seu `.ics` é:

```
https://raw.githubusercontent.com/SEU-USUARIO/morumbi-ical/main/morumbis.ics
```

- **Google Calendar**: "Outras agendas" → "+" → "Da URL" → cole o link acima.
- **Apple Calendar (iPhone/Mac)**: Ajustes → Calendário → Contas → Adicionar
  Conta → Outra → "Adicionar calendário assinado" → cole o link.
- **Outlook**: Adicionar calendário → Assinar da Web → cole o link.

Todos esses apps verificam a URL periodicamente (geralmente algumas vezes
por dia) e atualizam o calendário sozinhos — você não precisa reimportar o
arquivo manualmente.

---

## Rodando localmente (sem GitHub Actions)

```bash
pip install -r requirements.txt
python build_ics.py                     # gera morumbis.ics com jogos + shows
python build_ics.py --no-shows          # só jogos (mais confiável)
python -m scraper.games                 # só testa/imprime os jogos no MorumBIS
python -m scraper.games --debug         # imprime TODOS os jogos (não só MorumBIS), em JSON
python -m scraper.shows --debug         # imprime os candidatos a show, em JSON
```

## Se o site oficial mudar de estrutura (scraper para de achar jogos)

O parser de jogos (`scraper/games.py`) foi feito para não depender de
classes CSS específicas — ele localiza os jogos pelo padrão de texto da
data (`DD/MM/AAAA`) e sobe na árvore HTML até achar o bloco do jogo. Isso o
torna resistente a pequenas mudanças visuais, mas uma reforma grande do site
pode quebrá-lo. Para diagnosticar:

```bash
python -m scraper.games --debug
```

Se a lista vier vazia ou com nomes de time errados, abra
`https://www.saopaulofc.net/calendario-de-jogos/` no navegador, inspecione
o HTML de um card de jogo (botão direito → Inspecionar) e ajuste as
funções `_climb_to_card`, `_extract_venue` ou `_extract_teams_and_score`
em `scraper/games.py` de acordo com a nova estrutura.

O workflow do GitHub Actions **não sobrescreve o `.ics` anterior** se o
scraper não encontrar nada (jogos E shows vazios) — ele falha o job em vez
de publicar um calendário vazio, então você vai ver o alerta de falha por
e-mail/notificação do GitHub em vez de perder os dados silenciosamente.

## Limitações conhecidas

- **Shows/eventos têm taxa de erro real.** O extrator de datas
  (`dateparser`) lê texto livre em português e pode errar, duplicar ou
  deixar passar datas — especialmente quando a notícia menciona várias
  datas no mesmo texto (ex: "shows nos dias 19, 21, 22 e 25"). Por isso
  esses eventos entram como `TENTATIVE`/"a confirmar": trate-os como um
  lembrete pra você ir confirmar no site oficial ou na notícia linkada, não
  como verdade absoluta.
- O scraper de jogos depende de o site oficial continuar listando o nome
  do local da partida como "MorumBIS" (ou variações como "Morumbi"/"Cícero
  Pompeu de Toledo") — isso é tratado em `scraper/utils.py::VENUE_ALIASES`,
  edite essa lista se o clube trocar o nome de novo.
- Horário de jogo "A definir" entra como evento de dia inteiro (sem hora),
  pra não inventar um horário que não existe ainda.
