# Decisões de arquitetura

Cada decisão registra as alternativas consideradas e a justificativa. A numeração é a do registro original; as decisões sobre o protótipo anterior ao projeto e sobre o período de uso apenas local não constam desta versão.

## D-02. Armazenamento: SQLite + FTS5 + arquivos

- **Decisão:** SQLite (biblioteca padrão) como fonte de verdade dos metadados, relações, evidências e lacunas. FTS5 para a busca por dispositivo. Originais e Markdown ficam em arquivos.
- **Alternativas consideradas:**
  - só arquivos e JSON (abordagem de um protótipo anterior): sem consultas relacionais nem busca eficiente, e com risco de inconsistência entre manifestos;
  - DuckDB: analítico, sem FTS maduro equivalente;
  - PostgreSQL: exige servidor.
- **Justificativa:** SQLite é gratuito, local, um arquivo só, com FTS5 nativo e backup simples. Atende §6, §9 e §13 sem infraestrutura.

## D-03. Conversão de PDF: PyMuPDF (Fase 3 em diante)

- **Decisão:** PyMuPDF, com remoção de cabeçalho e rodapé pela posição na página. Poppler fica como alternativa se o desempenho em amostras reais for pior.
- **Alternativas consideradas:**
  - Poppler `pdftotext`: muito bom no benchmark inicial, mas exige binário externo no Windows;
  - `pypdf` em modo layout: saída ruim na Instrução 400;
  - Docling: lento e com estrutura ruim;
  - `pdfplumber`: reservado para tabelas.
- **Licença:** PyMuPDF é AGPL. Desde a publicação (D-23), o código do projeto é distribuído sob a GNU AGPL v3, compatível com ela.
- **Escopo atual:** a Fase 2 trata só a íntegra em HTML, por decisão do mantenedor.

## D-04. Interface: FastAPI + Jinja2

- **Decisão:** servidor local em `127.0.0.1`, com telas HTML simples e uma API JSON no mesmo processo.
- **Alternativas consideradas:**
  - Streamlit: rápido de montar, mas sem API para integrar com IA;
  - Datasette: ótimo para explorar dados, menos adequado à exportação jurídica.
- **Justificativa:** um só servidor atende a pesquisa (§9) e a futura integração com IA/MCP (§12).

## D-05. Pasta de dados configurável e fora do Git

- **Decisão:** `config.toml` define a pasta de dados (padrão `dados/` na raiz do projeto, que fica fora do OneDrive). Os originais ficam em armazenamento endereçado por SHA-256 e nunca são sobrescritos. `dados/` está no `.gitignore`.

## D-07. Conduta de coleta

- **Decisão:**
  - intervalo mínimo padrão de 3 s por host, configurável, com piso de 1 s;
  - uma requisição por vez;
  - retentativas com espera exponencial (até 3) para 5xx e falhas de rede;
  - parada imediata do lote em 401, 403 ou 429;
  - `robots.txt` auditado;
  - uso de ETag e Last-Modified.
- **Alternativas consideradas:** o piso rígido de 5 s de um protótipo anterior (conservador, mas inflexível); os 1 a 2 s sugeridos pela especificação.
- **Justificativa:** 3 s mantém a conduta conservadora e torna viável a coleta de cerca de 5 mil requisições (cerca de 4 h).

## D-08. Gabarito definitivo e escopo da Fase 2

- **Data:** 27/10/2026.
- **Decisão:** o mantenedor entregou o gabarito definitivo de 32 atos, que substitui a amostra provisória da §19. Nesta etapa, só a íntegra em HTML é coletada e convertida.
- **Atos sem íntegra em HTML:** ficam registrados como pendentes, com a ficha (evidência) e os links de PDF/DOCX anotados.

## D-09. Situação normativa a partir da ficha oficial e da cláusula de vigência

- **Data:** 27/10/2026.
- **Decisão:** a situação é derivada só de evidência documental registrada (§7), nesta ordem:
  1. **Revogada:** marcação "REVOGADA pela..." ou "(Revogada)" no título da ficha. Fica "parcialmente revogada" se a marcação disser "parcialmente"; caso contrário, "integralmente revogada".
  2. **Vigência futura:** a cláusula "entra em vigor em <data>" da íntegra oficial indica uma data posterior à da coleta.
  3. **Vigente com alterações:** marcação "ALTERADA pela(s)..." na ficha, sem marcação de revogação.
  4. **Vigente:** a ficha oficial não tem marcação de revogação nem de alteração. O fundamento registrado é exatamente esse ("ficha sem marcação…, consultada em <data>").
  5. **Não verificado:** quando a ficha não pôde ser lida.
- **Ressalva:** a ausência de marcação é uma evidência mais fraca que a marcação expressa. Por isso:
  - toda situação mostra o trecho que a fundamenta;
  - a situação depende da conferência manual, feita no gabarito;
  - a revogação pelo corpo de outra norma ("Fica revogado o inciso III do art. 31...") ainda não é cruzada automaticamente. Isso fica pendente para a Fase 3.
- **Alternativa descartada:** marcar "não verificado" sempre que não houvesse marcação. Seria inconsistente, porque também tornaria "vigente com alterações" uma inferência, e deixaria a situação inútil para a maior parte do acervo.

## D-10. Versionamento por hash; requisições condicionais de pouca utilidade na CVM

- **Data:** 27/10/2026.
- **Observação:** o portal `conteudo.cvm.gov.br` responde às fichas com `Last-Modified` igual ao horário da requisição e sem `ETag`. Por isso, a requisição condicional não evita downloads de fichas; nas íntegras `.htm`, o `Last-Modified` é estável.
- **Decisão:**
  - a detecção de mudança se faz pelo SHA-256 do conteúdo;
  - um hash novo gera um novo arquivo original, e o anterior é preservado;
  - o cliente continua enviando `If-Modified-Since` quando tiver o valor.
- **Exemplo:** a ficha da Res. 249 mudou de hash entre 21/10 e 27/10/2026.

## D-11. Conversão de PDF/DOCX: fonte por ordem de preferência e conferência cruzada

- **Data:** 27/10/2026. Aprovada pelo mantenedor ("DOCX + PDF nas resoluções, Res. 175 por último").

- **Fonte, por ordem de preferência:**
  1. Íntegra HTML oficial.
  2. DOCX oficial. A leitura é feita direto no OOXML com lxml, sem `python-docx`, e inclui:
     - a numeração automática do Word, reconstruída a partir do `numbering.xml`;
     - as notas de rodapé, incorporadas ao fim do texto.
  3. PDF oficial (PyMuPDF), usado quando não há DOCX. Isso cobre os ofícios, os pareceres e as redações originais.
  - O `.doc` binário (pareceres, Res. 9 consolidada) não é lido; nesses casos usa-se o PDF.

- **Conferência:**
  - **Interna:** todas as palavras da fonte precisam estar no Markdown.
  - **Cruzada (DOCX x PDF do mesmo texto):** cobertura mínima de 99,5% das palavras nos dois sentidos, sem diferenciar maiúsculas de minúsculas. O Word aplica caixa alta por formatação.
    - Para limpar o PDF, removem-se dele só os cabeçalhos e rodapés presentes no próprio DOCX.
    - A heurística de repetição foi descartada: removia linhas reais do corpo (Res. 80, Res. 247).
    - A similaridade de sequência é só informativa, porque as notas de rodapé mudam de posição.
  - **PDF sem DOCX:** a qualidade é "média". Não há segunda fonte para conferir, e a divisão em parágrafos é reconstruída.

- **Legibilidade:** um PDF cuja camada de texto é ilegível não gera Markdown. É o caso de fonte sem mapeamento Unicode, comum no SEI: caracteres de controle acima de 1% ou palavras comuns do português abaixo de 12%. O documento fica pendente com o motivo "exige OCR".

- **Versões guardadas:**
  - "texto consolidado oficial" e "texto original" são versões separadas.
  - A pesquisa usa o consolidado por padrão (`--versao original` para a outra).

- **Estilo `NormaAlterada`:**
  - Na redação original, marca o texto de outra norma que está sendo alterada.
  - No consolidado, marca o próprio texto vigente. Ali, a citação é reconhecida só pelas aspas.

- **Partes com articulado próprio:** os dispositivos levam a parte, por exemplo "Anexo Normativo I, art. 40" (migração v2 do banco).

- **Vigência:**
  - Quando o consolidado traz redações sucessivas da cláusula de vigência, nenhuma data é preenchida automaticamente. Os trechos ficam como evidência.
  - Exemplo: a Res. 175 tem "3 de abril de 2023" e "2 de outubro de 2023".
  - A data de 03/04/2023, tirada da redação original, foi removida. O motivo ficou registrado em `evidencia`.

- **Alternativas descartadas:**
  - Poppler: binário externo.
  - `pypdf`: saída ruim no benchmark inicial.
  - Docling: lento.
  - `python-docx`: não reconstrói a numeração automática.

## D-12. OCR com o Tesseract embutido no PyMuPDF

- **Data:** 27/10/2026. O mantenedor autorizou a instalação do Tesseract.
- **Decisão:** usar o motor do Tesseract que já vem no PyMuPDF (`get_textpage_ocr`, 300 dpi). Ele só precisa do modelo de idioma.
  - Modelo: `ferramentas/tessdata/por.traineddata`, de https://github.com/tesseract-ocr/tessdata_best.
  - SHA-256: `711de9db…adb04`, 8,2 MB.
  - O modelo fica fora do Git. O `instalar.bat` o baixa.
  - **Não foi instalado nenhum programa no Windows e nenhuma configuração do sistema foi alterada.**
- **Caminho com acento:** a biblioteca em C não abre caminhos com acento ("Laboratório"). No Windows, usa-se o nome curto 8.3 da pasta.
- **Quando é usado:** só quando a camada de texto do PDF é ilegível (D-11).
- **Qualidade:** sempre "baixa", com "conferência manual obrigatória antes de citar". Há erros típicos de OCR em e-mails, siglas e tabelas.
- **Verificação mínima:** pelo menos 75% das palavras da ementa da ficha oficial devem aparecer no texto, e as ausentes são listadas.
  - O limiar não é 90% porque a ementa da ficha pode parafrasear o documento. No Ofício SSE 02/2026, "Esclarecimento sobre... CRIs" aparece no texto como "CRI", sem a palavra "esclarecimento".
  - A checagem serve para detectar texto ilegível ou documento trocado. Não substitui a conferência.
- **Alternativas descartadas:**
  - Instalar o Tesseract ou o `ocrmypdf` no Windows: instalador externo e configuração de PATH, desnecessários.
  - OCR em serviço online: pago e envia o documento a terceiros.

## D-13. Redação anterior (tachado) e notas de alteração nos textos consolidados

- **Data:** 27/10/2026. Apontado pelo mantenedor na Res. 60 (art. 25, IV, "b").
- **Regra da CVM, conferida no DOCX oficial:** nos consolidados, a redação substituída continua no texto, mas tachada (`w:strike`). Logo depois vem a redação vigente e, em seguida, uma nota com marcador, por exemplo "Alínea b com redação dada pela Resolução CVM nº 194 de 17 de novembro de 2023".
- **Decisão:**
  - **Parágrafo inteiramente tachado:** é classificado como `redacao_anterior`. No Markdown fica `~~riscado~~`, guardado para o histórico. Sai da pesquisa e da busca por artigo e não conta para a cláusula de vigência.
  - **Tachado parcial:** o Markdown marca o trecho com `~~ ~~`, e o dispositivo pesquisável fica só com o texto vigente.
  - **Nota de alteração** ("com redação dada / incluído / revogado... pela"): é classificada como `nota_alteracao`, ligada ao dispositivo. A norma citada vira evidência da relação `alterada_por`.
  - **Marcadores de lista do Word** (glifos da fonte Symbol em área de uso privado, como U+F0B7) passam a ser exibidos como "•". Antes apareciam como "?".
- **Vigência:** prefere-se a cláusula do consolidado, já sem a redação tachada.
  - Res. 175: "3 de abril de 2023" estava tachado. A data passou a 02/10/2023, e a substituição ficou registrada em `evidencia`.
- **Conferência:** as 238 notas citam normas alteradoras que constam todas das fichas oficiais, nas 13 normas com notas.
- **Limitação:** a íntegra HTML e os PDFs não trazem a formatação de tachado, então só o DOCX permite essa distinção. A redação original não tem tachado.

## D-14. Decodificação de fontes Type3 dos PDFs do SEI, no lugar do OCR

- **Data:** 28/10/2026. Pedido do mantenedor: revisar à mão um texto inteiro obtido por OCR não é viável.
- **Diagnóstico:** os Ofícios SSE 02/2026 e 03/2026 foram "impressos" do SEI em PDF (PDF24 e Ghostscript). O texto virou uma fonte Type3 sem `ToUnicode`: cada letra é um desenho vetorial (CharProc) com um código próprio. Cada página tem sua própria fonte, e os códigos se repetem entre as fontes.
- **Decisão:**
  - O texto passa a ser decifrado da própria fonte. A identidade de cada desenho é o SHA-1 do seu programa, então o mesmo desenho é a mesma letra, em qualquer página ou documento.
  - O OCR é usado só para identificar as letras, por votação nas linhas pareadas. O deslocamento vertical entre linhas é escolhido pelo maior número de linhas com a mesma contagem de caracteres.
  - Depois vêm rodadas de refinamento por alinhamento de sequências. O mapa obtido é aplicado à camada de texto original.
- **Caractere incerto:** concordância abaixo de 75% ou sem voto.
  1. Primeiro tenta-se o léxico dos textos oficiais já convertidos. Entre as letras votadas, decide a que forma palavras existentes, desde que valide pelo menos 80% das palavras com folga de 30 pontos, ou forme 2 ou mais palavras enquanto as alternativas não formam nenhuma.
  2. Depois tenta-se o dicionário de glifos do acervo (tabela `glifo`, migração v3), que guarda desenhos com concordância de 90% ou mais e pelo menos 5 votos, e marca conflito entre documentos.
  3. Sem resolução, o caractere fica como "□". Nunca é adivinhado.
- **Qualidade:** "média", com a contagem de caracteres não identificados. Se mais de 10% dos caracteres ficarem incertos, volta-se ao OCR (D-12), com qualidade "baixa".
- **Resultado:**
  - SSE 03/2026: 1,3% de caracteres incertos.
  - SSE 02/2026: 4,7%.
  - No corpo dos ofícios restam só a "@" dos e-mails e um "ú". Os demais □ estão no timbre, na assinatura eletrônica e no rodapé do SEI.
- **Alternativas consideradas:**
  - Outro OCR (PaddleOCR, docTR): mantém erros pontuais e é pesado.
  - Versão do SEI: exige CAPTCHA, que o projeto não contorna.
  - DOU: ofícios-circulares, em regra, não são publicados nele (não confirmado na base do DOU).

## D-15. Interface, exportação e atualização incremental (Fase 3)

- **Data:** 28/10/2026. A conferência do gabarito foi adiada pelo mantenedor para depois da Fase 3, e o acervo permanece com os 32 atos.
- **Interface:** FastAPI com Jinja2 (D-04), servida só em 127.0.0.1 e sem acesso de escrita ao banco.
  - O link de cada resultado leva ao dispositivo pelo fragmento de texto (`#:~:text=`). Não são criadas âncoras no Markdown.
  - Uma API JSON local (`/api/pesquisa`, `/api/norma/{id}`) atende o §12: devolve o trecho com a norma, o dispositivo, a redação, a situação, a data de referência e a URL oficial. A camada MCP fica para a Fase 5, se for desejada.
- **Markdown → HTML** (markdown-it, sem plugins):
  - itens numerados e marcadores ficam literais;
  - notas de rodapé são tratadas pelo próprio projeto, porque o plugin renumerava as notas e descartava as sem chamada (Res. 80 e 175);
  - não há linha horizontal, porque "____" é campo de formulário;
  - "a*b" fica literal.
- **PDF:** fpdf2 com as fontes Arial do Windows, mais a Segoe UI Symbol para "□".
  - O PyMuPDF Story foi descartado porque perdia texto nas quebras de página e em linhas de tabela mais altas que a página.
  - Todo PDF é conferido palavra por palavra contra o Markdown. Palavras partidas pelo layout são aceitas se aparecerem no texto sem espaços. Se faltar texto, a exportação falha.
  - Verificação real: 256 exportações das 64 versões aprovadas.
- **Word:** python-docx. Mantém tachado, negrito, itálico, tabelas e o cabeçalho de identificação.
- **Atualização incremental:**
  - A ficha é comparada pelo conteúdo lido, não pelo hash do HTML (D-10).
  - Arquivo de texto com hash novo vira uma nova versão. As diferenças são registradas por dispositivo, e nada é apagado.
  - As publicações novas vêm da 1ª página do catálogo de cada família. A primeira leitura serve só de base, porque não dá para saber o que é "novo" sem uma leitura anterior (tabela `catalogo_visto`, migração v4).
  - As publicações novas não são baixadas automaticamente nesta fase.
  - A rotina é retomável: as normas verificadas há mais tempo vêm primeiro.

## D-22. Coleta histórica a partir do catálogo oficial (Fase 4)

- **Data:** 06/11/2026. Pedido do mantenedor: piloto por espécie e, em seguida, a coleta completa das resoluções.
- **Fonte da lista:** a última leitura completa do catálogo de cada família (D-16). Um ato já presente no acervo é reconhecido pela URL da ficha.
- **Comando:** `coletar-catalogo` (`coletar-catalogo.bat`), com as opções `--familia`, `--amostra N` (piloto: N atos por família, espalhados do mais antigo ao mais recente) e `--limite`.
  - A coleta é retomável: os atos já verificados são pulados.
  - Um erro inesperado num ato vai para o log e não interrompe a coleta.
  - Ao fim, roda a consolidação e a biblioteca.
- **Identificadores:**
  - padrão do acervo: "resolucao-cvm-175", "oficio-circular-conjunto-cvm-sin-sse-01-2025", "nota-explicativa-resolucao-cvm-50";
  - colisão (dois ofícios com o mesmo número no catálogo) recebe o nome da ficha na URL como sufixo;
  - ano de ofício com dois dígitos: 76 a 99 é 19xx.
- **Correções feitas pelo piloto:**
  - **Fichas das instruções:** os links das marcações ("ALTERADA pela Instrução 30/84", "REVOGADA pela Instrução 247/96", "VIDE ...") apontam direto para o PDF da outra norma. O leitor de fichas os tomava por íntegra desta norma, e a Instrução 1 chegou a exibir como "texto original" a Instrução 247.
    - Agora esses links são relações.
    - Arquivo cujo nome identifica outra norma (inst015.pdf na ficha da inst001) nunca é texto desta, nem na leitura da ficha nem na conversão.
    - Os registros já gravados foram corrigidos com autorização do mantenedor, sem apagar nada, com backup em `acervo-20261106-145407-manual.sqlite`: 33 arquivos e 35 links passaram ao papel "citado", e 8 versões foram reprovadas com o motivo.
  - **Texto oculto do Word (`w:vanish`):** não é impresso nem está no PDF, e passa a ser ignorado (conversor DOCX v9). Na Res. 92 eram segmentos em inglês de memória de tradução.
- **Quando o DOCX diverge do PDF:** em resoluções de pronunciamentos contábeis, diagramas, caixas de texto e numeração automática fazem o DOCX divergir do PDF. A regra da D-11 deixava esses atos sem texto. Agora o texto vem do PDF, com qualidade "média" e o aviso de que o DOCX divergiu, como nos atos que só têm PDF. A versão do DOCX continua registrada como "revisar". Vale o mesmo para o HTML reprovado quando há DOCX ou PDF da íntegra (Res. 217).
- **Só os não revogados (`--sem-revogados`):** pedido do mantenedor em 06/11/2026. O filtro usa a marca "(Revogada)" do título no catálogo, que é só uma pré-seleção: a situação de cada ato vem da ficha (D-09). O catálogo não marca ofícios nem pareceres, deixa sem marca notas explicativas revogadas (70 de 76, segundo as fichas) e 18 resoluções revogadas.
- **URL proibida pelo `robots.txt`:** o ato é pulado e a tentativa fica registrada como "proibido pelo robots.txt"; a coleta segue. Só a coleta do catálogo pula; nos outros comandos continua valendo a parada, como em qualquer bloqueio. Os bloqueios do servidor (401/403/429) continuam interrompendo a coleta inteira. Caso real: a ficha da Deliberação 233, proibida por processo SEI.

## D-21. Versão consolidada (só o texto vigente) e três versões por norma alterada

- **Data:** 28/10/2026. Pedido do mantenedor: uma versão "consolidada" das normas alteradas, só com o texto atual, sem a redação antiga tachada. Respostas do mantenedor: manter as notas de alteração; quando não houver consolidado utilizável, gerar a consolidação; aplicar também as alterações que o consolidado oficial ainda não incorpora, mantendo sempre as versões original, alterada com tachado e consolidada.
- **Três versões por norma alterada** (`versao_texto.tipo`):
  - `texto original`;
  - `texto consolidado oficial`: o consolidado da CVM, com a redação anterior tachada ("Alterada, com tachado");
  - `texto consolidado vigente`: só o texto vigente ("Consolidada"). Passa a ser a versão padrão da página, da pesquisa e da exportação, com recuo para o consolidado oficial e depois para a original;
  - `texto alterado com tachado (gerado)`: quando o sistema aplica alterações (etapas 2 e 3 abaixo).
- **Etapa 1: derivação do consolidado oficial em DOCX (`consolidacao.py`, conversor `consolidacao-limpa/1`).**
  - Saem os blocos de redação anterior, os trechos `~~ ~~` dos parágrafos e os `<s></s>` das tabelas. Sai também a linha de tabela que fica vazia e a definição de nota de rodapé cuja chamada só existia no trecho tachado.
  - Ficam as notas de alteração e as demais notas de rodapé.
  - A versão nova aponta para a de origem (`base_versao_id`, migração v8). Os dispositivos são os do consolidado oficial, menos os de redação anterior.
  - **Conferência:** as palavras do Markdown novo devem ser exatamente as dos dispositivos mantidos, e todas devem estar no Markdown de origem. Sem isso, a versão fica reprovada e não é exibida.
- **Tachado em tabelas (conversor DOCX v5):** até a v4, as células eram lidas sem a formatação, e a redação anterior das tabelas aparecia como texto vigente. No DOCX oficial havia 4.301 trechos riscados em tabelas na Res. 80, 607 na Res. 175, 308 na Res. 60 e 9 na Res. 21. Agora o trecho riscado fica entre `<s></s>` no HTML da tabela (o Markdown não é lido dentro de HTML) e fora do texto pesquisável. Tabela inteiramente riscada é redação anterior.
- **Consolidado oficial só em PDF (Res. 9):** não é derivado, porque o PDF não marca o tachado (D-13). A consolidação é gerada pela aplicação das alterações à redação original (etapa 3).
- **Aviso:** a página e a exportação dizem de onde vem cada versão. A consolidação gerada pelo sistema leva sempre "consolidação gerada automaticamente, não oficial" (§7 da especificação).
- **Etapa 2: normas alteradoras e motor de aplicação (`alteracoes.py`, `motor_alteracoes.py`).**
  - **Quais alteradoras:** as das relações `alterada_por` (ficha da norma alterada) e `altera` (ementa da alteradora, caso da Res. 247) das normas do gabarito.
    - As alteradoras ausentes são coletadas como documentos comuns, só com ficha e redação original (`coletar-alteradoras`, também ao fim de `atualizar`).
    - As relações das próprias alteradoras não são seguidas, para a coleta não se estender em cascata.
  - **Comandos reconhecidos:**
    - "passa a vigorar com a seguinte redação / com as seguintes alterações / acrescido de";
    - "Fica(m) revogado(s)", com a lista de dispositivos;
    - parte citada ("o Anexo II da Resolução...").
  - **Como o texto citado é lido:** é estruturado como um trecho de norma. Uma linha só com rótulo e pontilhado mantém o dispositivo. Um dispositivo que já existe recebe a redação nova, e a anterior fica tachada. Um dispositivo que não existe é incluído depois do irmão anterior; título citado vai junto.
  - **Nota gerada:** cada alteração recebe uma nota no formato da CVM, marcada "(alteração aplicada automaticamente)". Subdispositivo de dispositivo incluído no mesmo comando não ganha nota própria.
  - **O que não é aplicado:** substituição ou inclusão de anexo inteiro ("na forma do Anexo desta Resolução"), formulários e comando sem texto citado reconhecível. Esses casos, e o dispositivo não localizado, nunca são aplicados por suposição. Ficam em `alteracao_aplicada` com status e na página da norma.
  - **Parágrafo partido pelo PDF:** no texto vindo de PDF, o parágrafo que passa de página pode virar dois blocos. A continuação ("texto" sem rótulo, depois de item que não termina em . ; :) é tratada como parte do dispositivo.
- **Validação contra a CVM (`validar-consolidacao`, relatório em `dados/relatorios`):** aplicam-se à redação original as alteradoras citadas no consolidado oficial e compara-se com a consolidada derivada do oficial, dispositivo a dispositivo.
  - Resultado de 28/10/2026: entre 97,6% e 100% em 10 das 14 normas (Res. 32: 100%).
  - Abaixo disso:
    - Res. 160: 92,6%;
    - Res. 60: 82,1%;
    - Res. 80: 71,3%;
    - Res. 175: 40%, porque os Anexos Normativos III a XII foram incluídos por anexo inteiro;
    - Res. 179: 25,5%, porque é ela própria alteradora, e o texto citado não é comparável.
  - As causas são a estrutura da redação original convertida de PDF e comandos não suportados.
  - Por isso, a consolidação gerada parte do consolidado oficial em DOCX sempre que ele existe.
- **Etapa 3: o que é gerado.**
  - **Pendentes:** com consolidado oficial em DOCX, são pendentes as alteradoras que nenhuma nota dele cita e que são posteriores à última citada. Sem consolidado em DOCX, parte-se da redação original com todas as alteradoras.
  - **Vigência:** a versão com tachado inclui as alterações com vigência futura, com a data na nota. A consolidada só inclui as que estão em vigor na data da geração.
  - **Sem alteração em vigor a aplicar:** a consolidada continua a derivada do oficial. Uma consolidada gerada que não aplicou nada nunca substitui a derivada.
  - **Regeneração:** a assinatura da geração inclui as alteradoras e quais estão com vigência futura. Quando a data chega, `consolidar` (também ao fim de `atualizar`) gera a versão nova.
  - **Conferência:**
    - a versão com tachado não perde nenhuma palavra do texto de partida;
    - a consolidada tem exatamente as palavras dos dispositivos vigentes;
    - sem consolidado em DOCX, ela é comparada com o consolidado oficial em PDF, sem as notas geradas.
- **Correções feitas no caminho:**
  - **Notas "§ 1º com redação dada..." e "Art. 13 com redação dada..."** não eram reconhecidas como notas de alteração (D-13). O `` depois de "§" e de "Art." não casava. Elas viravam um "§ 1º" duplicado no texto. Agora, para "§" e "Art.", o verbo deve vir logo depois do número, para não confundir um artigo que tenha "incluído pela" no texto.
  - **Conferência DOCX × PDF:**
    - usa o PDF de mesmo nome do DOCX (Res. 181 tem também o "Sumário Executivo");
    - separa o número de nota de rodapé colado à palavra no PDF ("iii1").
  - **Exportação em PDF:** o fpdf2 não aceita tachado em célula de tabela. Ali, a redação anterior sai como "[redação anterior: ...]".

## D-20. Biblioteca legível sobre os originais por hash

- **Data:** 28/10/2026. Pedido do mantenedor: organizar melhor os documentos guardados (os originais por hash não são navegáveis).
- **Decisão:** `dados/originais` continua endereçado por SHA-256 (imutabilidade, sem duplicação, conferência pelo `verificar`). Sobre ele, `dados/biblioteca` é uma visão gerada do banco, com pastas por espécie e por norma, audiências dentro da norma e numa pasta própria, e um `LEIAME.txt` por pasta com metadados e a origem (URL, data, SHA-256) de cada arquivo.
- **Vínculos físicos (hard links)** em vez de cópias: o acervo completo pode chegar a alguns GB, e cópias dobrariam o espaço. Como vínculo e original são o mesmo arquivo, todo original passa a ter o atributo "somente leitura" (também no momento da gravação). Sem suporte a vínculos, copia-se. As conversões em Markdown são copiadas, porque o conversor as regrava.
- **Segurança da regeneração:** a nova biblioteca é montada em `biblioteca.nova` e só substitui a anterior se esta tiver a marca `.biblioteca-gerada`; uma pasta `biblioteca` criada à mão nunca é apagada. Apagar um vínculo não apaga o original.
- **Nomes:** compatíveis com o Windows ("/" vira "-") e curtos (limite de 260 caracteres no caminho); o primeiro arquivo da seção da audiência chama-se "Edital" ou "Relatório", os seguintes levam o que os distingue ("Edital - Aviso de Prorrogação"). O rótulo oficial completo fica no LEIAME.
- **Alternativas descartadas:** reorganizar `originais` por nome (perde a imutabilidade por hash e quebra o banco); atalhos `.lnk` (não abrem bem em outros programas); junções de pasta (risco de apagar o destino ao apagar a biblioteca).

## D-19. Audiências públicas das normas (sem manifestações)

- **Data:** 28/10/2026. Pedido do mantenedor: edital e audiência pública das normas, principalmente RCVM 160 e 175; as manifestações recebidas não entram.
- **Fonte:** a ficha da norma cita a audiência ("AUDIÊNCIA PÚBLICA: SDM 02/21") com link para a página oficial `/audiencias_publicas/ap_<área>/<ano>/<código>.html`. A página tem seções fixas: Edital, Tema, Prazo para Manifestação, Fase, Manifestações recebidas, Relatório e Norma editada.
- **Decisão:**
  - a relação norma ↔ audiência é registrada com evidência de cada origem: a ficha da norma e a seção "Norma editada" da página da audiência. Ficha sem audiência não prova que não houve audiência; nada é registrado nesse caso;
  - são baixados como originais imutáveis só os arquivos das seções Edital (edital, aviso de prorrogação, anexos) e Relatório, e convertidos em texto pesquisável (camada de texto do PDF, qualidade "média"). Os links das demais seções ficam registrados; as manifestações não são lidas;
  - o prazo é guardado como a página o exibe e, à parte, como o edital o declara ("Prazo: 2 de abril de 2021"). Um não corrige o outro: a página pode mostrar o prazo prorrogado ou o horário do servidor (ex.: "Sat Feb 12 00:59:00 BRST 2022" na SDM 08/21);
  - os arquivos ficam na tabela `arquivo` sem `documento_id`, para que o `verificar` confira também o hash deles.
- **Alternativa descartada:** baixar por endereço deduzido (ex.: `sdm0820_Relatorio.pdf`). Na SDM 08/20 esse endereço existe, mas a página aponta para outra versão, revisada (`..._vRevisada_Res_181_e_184.pdf`). Só se segue o que a página lista.

## D-18. Partes das normas com anexos (Parte Geral, Anexos, Suplementos)

- **Data:** 28/10/2026. Pedido do mantenedor: poder selecionar a parte geral e cada anexo de normas como a RCVM 175.
- **Decisão:** a divisão vem do próprio texto convertido (títulos "ANEXO ..." e "SUPLEMENTO ..."), gravada em `dispositivo.parte`. Como cada bloco do Markdown é um dispositivo, a parte é recortada do Markdown sem reconversão. Os nomes completos e os PDFs oficiais por parte vêm da ficha quando ela os lista (Res. 175); os PDFs por parte da ficha são do consolidado e só aparecem nessa versão.
- **Correções do conversor (versões 4, reconversão completa):**
  - linhas de sumário com pontilhado não abrem parte, nem quando a entrada quebra em duas linhas (no PDF original da Res. 175, o sumário fazia a Parte Geral virar "Anexo Normativo II");
  - "Anexo I." solto (fim de remissão quebrada pela paginação) não é título de anexo;
  - suplementos formam a parte "Suplementos", como na ficha da CVM; antes ficavam dentro do último anexo;
  - nota de rodapé pertence à parte em que é chamada.
- **Alternativa descartada:** baixar e converter os PDFs por parte da ficha. O consolidado completo já contém todas as partes, conferido com o PDF; os PDFs por parte só existem para a Res. 175 e não têm DOCX para conferência cruzada.

## D-17. Cliente HTTP próprio

- **Data:** 28/10/2026.
- **Decisão:** cliente HTTP, modelo do arquivo baixado e testes do cliente com implementação própria.
- **Melhorias incluídas:**
  - corpo menor que o "Content-Length" anunciado é baixado de novo, em vez de virar original;
  - cada download informa o formato esperado (pdf, docx, html), e uma página de erro servida no lugar do arquivo é recusada e registrada como lacuna;
  - "Retry-After" de até 5 minutos é respeitado uma vez nos códigos 429 e 503; a repetição continua sendo bloqueio;
  - o `robots.txt` é relido a cada 6 horas em coletas longas, e o `Crawl-delay`, se existir, prevalece sobre os 3 s quando for maior;
  - limite de 200 MB por arquivo, lido em blocos;
  - os redirecionamentos do `robots.txt` seguem a regra geral da RFC 9309, sem o caso especial de servidores da CVM do código anterior;
  - foi retirado o cache em disco que não era usado, porque os originais já ficam guardados por hash.
- **Mantido:** a auditoria do `robots.txt` em cada redirecionamento, o intervalo por servidor, as novas tentativas com espera crescente, a parada imediata em bloqueio, a requisição condicional e o registro JSONL de cada evento.

## D-16. Cobertura medida contra o catálogo oficial da CVM

- **Data:** 28/10/2026. Pedido do mantenedor: a página de cobertura deve mostrar o acervo em relação à base completa da CVM, e não só contar o que já está no acervo.
- **Referência:** a pesquisa de legislação do portal da CVM, lida em todas as páginas de cada família (`ler-catalogo`). A leitura guarda título, data, descrição e URL de cada ato, sem baixar fichas nem arquivos (migração v5: `leitura_catalogo` e `catalogo_oficial`).
- **Leitura completa:** só quando a quantidade de atos distintos lidos é igual ao total que a página informa ("N resultados encontrados"). Caso contrário, a família fica "incompleta" e o relatório avisa.
- **Comparação com o acervo:** feita pela URL da ficha. As URLs do catálogo e as do acervo conferem nos 32 atos do gabarito.
- **Ano:** é o da data exibida no catálogo, que coincide com a data de edição na amostra conferida (Res. 247, Del. 906, SSE 03/26).
- **Números ausentes:** nas espécies numeradas em sequência (resoluções, instruções, deliberações e pareceres), os números entre 1 e o maior listado que não aparecem no catálogo são apontados como "não localizado", nunca "inexistente".
- **Limite:** um ato que o próprio catálogo omita não é detectado por esta fonte. O cruzamento com o DOU fica para a Fase 4.
- **Retomada:** famílias com leitura completa nos últimos 7 dias não são relidas (`--refazer` força a releitura). Itens que saírem do catálogo não são apagados; apenas deixam de ser contados.

## D-23. Publicação aberta do código e do acervo

- **Data:** 09/11/2026. O projeto, até então de uso local, passa a ser público para que outras pessoas o usem.
- **Repositório:** https://github.com/OlimpioV/CVM-normas.
- **O que é publicado:** o código, os testes, a documentação pública (README, `docs/COMO-FUNCIONA.md`, `docs/FORMATO.md`, `docs/DECISOES.md`, `docs/fontes/`) e o acervo em Markdown (`acervo/`, gerado por `publicar-acervo`). O banco, os originais, os backups e os logs não são publicados: são grandes e reproduzíveis pela coleta.
- **Licenças:**
  - código: GNU AGPL v3 (exigida pelo PyMuPDF), com termo adicional da seção 7(b) que obriga a preservar o `CREDITOS.md`;
  - acervo (organização, metadados, origem, relações, consolidações geradas): CC BY 4.0, que exige atribuição;
  - textos das normas: atos oficiais, sem proteção autoral (Lei 9.610/1998, art. 8º, IV).
- **Créditos:** a organização do acervo em Markdown foi inspirada no ctresb/leis (João Davi, MIT). Não há código copiado dele; o reconhecimento é de inspiração e deve ser mantido por quem reutilizar este projeto (`CREDITOS.md`, `CITATION.cff`).
- **Formato do acervo:** um arquivo por norma em `acervo/<espécie>/<ano>/<id>.md`, com cabeçalho YAML (metadados, situação com fonte, URL e SHA-256 do arquivo convertido), índice por espécie e cobertura. A versão principal é a consolidada quando houver; a original fica ao lado (`.original.md`). Só versões aprovadas na conferência de fidelidade entram. Caracteres de controle de PDFs sem mapeamento Unicode viram "□". A geração é determinística.
- **Alternativas consideradas:**
  - publicar só o código: descartada; o valor para o público está sobretudo no acervo navegável;
  - licença MIT para o código: incompatível com a dependência AGPL (PyMuPDF).
- **Também:** exportação em PDF no Linux e macOS (DejaVu Sans), atalhos do Windows em `scripts/windows/`, dependências declaradas no `pyproject.toml`, GitHub Actions com os testes sem rede.
- **Vigentes e revogados (10/11/2026):** a tabela do acervo separa vigentes (vigente, vigente com alterações, vigência futura, parcialmente revogada) e revogados (integralmente revogada), no acervo e na CVM, com cobertura total e cobertura dos vigentes. Na CVM, os atos do acervo seguem a ficha oficial e os não coletados seguem a marca "(Revogada)" do catálogo, que é incompleta. O `publicar-acervo` reescreve essa tabela no `acervo/README.md` e no trecho marcado do README da raiz; o resto do README não é tocado.
- **Versão 1.0.0 (10/11/2026):** lançamento público com histórico de um único commit.

## D-24. Justificativas de dispensa de Análise de Impacto Regulatório (AIR)

- **Data:** 10/11/2026. Pedido do mantenedor: incluir a "Justificativa - Dispensa de Análise de Impacto Regulatório (AIR)" que aparece na ficha de várias resoluções, como é feito com as audiências públicas.
- **Situação encontrada:** 68 fichas citam a justificativa. Em 43, o link é um PDF anexo, que a ficha já registrava como "complementar", sem baixar. Em 25, é a página da decisão do Colegiado (`/decisoes/...`), que não era reconhecida porque não é arquivo de anexo.
- **Decisão:** documento próprio ligado à norma, como a audiência pública (D-19):
  - a ligação vem da ficha, com evidência (URL e SHA-256 da ficha e o rótulo do link); ficha sem o link não prova que não houve justificativa;
  - o documento é guardado como original imutável (papel `justificativa`) e convertido à parte: PDF pela camada de texto, DOCX, ou o texto da decisão (elemento `<article>` da página do Colegiado), com conferência de fidelidade;
  - tabela própria (migração v9), comando `coletar-justificativas` (retomável), página da norma, API, biblioteca e acervo público (`acervo/justificativas-air/<ano>/<norma>.md`, campo `justificativa_air` no cabeçalho da norma).
- **Fora do escopo:** relatórios de AIR completos e notas técnicas não citados na ficha; a rotina `atualizar` ainda não relê as justificativas (rodar `coletar-justificativas`).

## D-25. Legibilidade de anexos em tabela, versão em inglês e OCR de ficha sem ementa

- **Data:** 10/11/2026. Pedido do mantenedor: texto para os 3 atos vigentes que estavam sem ele.
- **Causas encontradas, uma em cada ato:**
  - Ofício-Circular SMI 02/2023: 3 páginas de ofício e 20 de tabela (ticker, ISIN, lote mínimo). A tabela quase não tem palavras comuns do português, e o teste de legibilidade (D-12) a confundia com fonte sem mapeamento Unicode. A camada de texto é exata; o OCR erraria os códigos;
  - Deliberação 339: a ficha traz também `deli339en.pdf`, e a versão em inglês era tomada como íntegra (e reprovada por não ter palavras do português);
  - Ofício-Circular SNC/GNA 01/18: digitalização, OCR legível, mas a ficha não tem ementa, e a conferência pela ementa dava 0%.
- **Decisão:**
  - legibilidade página a página quando o texto todo tem poucas palavras comuns: páginas com 100 termos ou mais devem ser prosa (palavras comuns >= 12%) ou tabela (metade ou mais dos termos com algarismos ou códigos maiúsculos), com ao menos uma página de prosa; páginas curtas (ex.: assinatura eletrônica do SEI) não entram na conta. Texto embaralhado continua recusado;
  - arquivo `<nome>en`/`<nome>_en` do mesmo papel e formato que `<nome>` é tratado como versão em inglês e não é texto do ato;
  - ficha sem ementa: o OCR é conferido pelo título do ato (conversor `pdf-ocr-tesseract/6`).
- **Resultado:** os 3 atos com texto aprovado (SMI 02/2023 e Deliberação 339 pela camada de texto, qualidade média; SNC/GNA 01/18 por OCR, qualidade baixa, 100% do título encontrado). Nenhum outro ato muda: as 27 versões por OCR existentes são de digitalizações sem camada de texto legível.
