> Pesquisa inicial sobre as fontes, feita em 21 a 27/10/2026. Insumo de pesquisa: conclusões a reconferir nas fontes oficiais antes de serem adotadas.

# Fontes oficiais para um corpus de normas CVM

Data da consulta: **21/10/2026**. Pesquisa HTTP real, sem coletor implementado e sem carga integral. Foram usados GETs com Python `requests`, inspeção do HTML recebido, XML/JSON e, em dois casos, download de bytes PDF em memória. Uma experiência com o endpoint interno também usou POST de consulta, sem criação de conteúdo. Linhas HTML abaixo referem-se à resposta recebida nesta data, não a números estáveis do portal.

`UNVERIFIED` significa que não houve confirmação suficiente; um HTTP 200 sozinho não demonstra dados corretos, cobertura ou licença. O conteúdo HTTP foi examinado em memória, sem acrescentar snapshots ou scripts ao repositório privado de origem.

## 1. As três entradas solicitadas

| URL efetivamente requisitada | Resultado | Papel observado |
|---|---|---|
| <https://www.gov.br/cvm/pt-br/assuntos/normas> | **200**, `text/html;charset=utf-8` | Página Plone de navegação, com cartões para resoluções, instruções, deliberações, notas explicativas e pareceres, além de agenda e consultas. Não é o corpus de textos integrais |
| <https://conteudo.cvm.gov.br/legislacao/resolucoes.html> | **200**, `text/html;charset=UTF-8` | Página temática: assuntos, formulário de busca, destaques e mais recentes. O recorte visível não é a lista completa |
| <https://conteudo.cvm.gov.br/legislacao/index.html> | **200**, `text/html;charset=UTF-8` | Busca por número, termos, intervalo de datas e categorias; resultados podem vir no HTML do GET parametrizado |

A página gov.br tem `meta generator=Plone` e serve principalmente navegação. O portal de conteúdo usa caminhos `/system/modules/br.com.squadra...`, formulários e jQuery; não foi necessário executar JavaScript para obter os resultados dos GETs de busca testados. A tecnologia de backend além desses vestígios é **UNVERIFIED**.

O índice geral exibe categorias legadas e não mostra uma caixa de resoluções no formulário inicial examinado; entretanto, a busca por `/legislacao/resolucoes/` funciona. Não construir cobertura apenas a partir dos checkboxes iniciais.

## 2. Tipos, organização e volume observado

Para cada uma das cinco famílias abaixo foi requisitado o mesmo padrão de URL: `https://conteudo.cvm.gov.br/legislacao/index.html?buscado=true&contCategoriasCheck=1&vimDaCategoria=/legislacao/<familia>/`. Todas responderam **200** e mostraram o número de resultados no HTML, sem estimar pelo maior número da série.

| Família / parâmetro real | Registros informados pela busca | Organização e exemplo confirmado |
|---|---:|---|
| `resolucoes` | **249** | [Página da Resolução 249](https://conteudo.cvm.gov.br/legislacao/resolucoes/resol249.html), ato de 13/10/2026 |
| `instrucoes` | **627** | [Instrução 400](https://conteudo.cvm.gov.br/legislacao/instrucoes/inst400.html), título explicitamente marcado como revogado; a busca começa em 627 no recorte recebido |
| `deliberacoes` | **907** | [Deliberação 907](https://conteudo.cvm.gov.br/legislacao/deliberacoes/deli0900/deli907.html); subpastas por faixa numérica, como `deli0900` |
| `pareceres-orientacao` | **41** | [Parecer de Orientação 40](https://conteudo.cvm.gov.br/legislacao/pareceres-orientacao/pare040.html); arquivos `pareNNN.html` |
| `oficios-circulares` | **600** | [Ofício Anual 2024 CVM/SEP](https://conteudo.cvm.gov.br/legislacao/oficios-circulares/sep/oc-anual-sep-2024.html); pastas por superintendência, inclusive atos conjuntos |

**Dimensão inicial: aproximadamente 2,4 mil registros de catálogo** nessas cinco famílias (soma aritmética: 2.424). Isso não é um censo deduplicado de normas vigentes, nem inclui todos os anexos, versões, portarias e demais tipos. Número de páginas PDF, bytes totais, proporção de OCR, total de dispositivos e completude histórica: **UNVERIFIED**.

Outros tipos realmente apresentados no índice: **decisões conjuntas, leis e decretos e notas explicativas**. O portal gov.br também aponta **portarias**, revisão/consolidação, audiências e consultas públicas. Consultas e agenda não devem receber automaticamente o mesmo estatuto de ato normativo publicado. As listagens de [deliberações](https://conteudo.cvm.gov.br/legislacao/deliberacoes.html), [pareceres](https://conteudo.cvm.gov.br/legislacao/pareceres-orientacao.html) e [ofícios](https://conteudo.cvm.gov.br/legislacao/oficios-circulares.html) responderam 200.

A listagem de ofícios distingue SEP, SIN, SMI, SNC, SRE, SOI, PTE, SGE, SSE e combinações como SMI/SIN ou SEP/SRE. Há inclusive link repetido para SNC/SSE e caminhos sem barra final. **Número isolado não identifica ofício**: usar órgão/unidade, tipo, número e ano, preservando a URL de origem. Atos declaratórios aparecem no catálogo de dados abertos, mas não são sinônimo de resoluções; incluí-los requer escopo próprio.

## 3. Estrutura das listagens e paginação

Na página de resoluções, `form#pesqAvancada` tem ação `/legislacao/index.html`, campo `numero`, termos em `lastName` e campos ocultos `buscado`, `pasta`, `filtro`, `contCategoriasCheck`, `vimDaCategoria` e `tags` (HTML L1458–1492). Os blocos de destaque/recentes trazem link da norma, data e descrição. A página inicial tem somente esses recortes, não paginação do acervo inteiro.

O GET abaixo retornou **249 resultados, 10 artigos e página 1/25**:

<https://conteudo.cvm.gov.br/legislacao/index.html?buscado=true&contCategoriasCheck=1&vimDaCategoria=/legislacao/resolucoes/>

O mesmo GET com `&searchPage=2` respondeu **200**, preservou 249 resultados, mostrou **página 2/25** e links da Resolução 239 até a 230. Isso comprova paginação real, não apenas presença de botões:

<https://conteudo.cvm.gov.br/legislacao/index.html?buscado=true&contCategoriasCheck=1&vimDaCategoria=/legislacao/resolucoes/&searchPage=2>

Os resultados ficam em `section.listaResultados`, com um `article` por resultado e título em `h3 > a`; há descrição, data e, quando presentes, etiquetas de assunto. A ordenação oferece `recentes` e `antigas`; o seletor de tamanho oferece **10, 20 e 50**. Apenas o tamanho 10 foi validado percorrendo duas páginas; o comportamento efetivo de 20/50 e de todas as páginas é **UNVERIFIED**.

A paginação usa `form.paginacao` e o endpoint **`/system/modules/br.com.squadra.legislacao/elements/resultadoLegislacao.jsp`**. O `form#formParam` mantém `searchPage`, termos, datas, `itensPagina`, `ordenar`, `listaBuscaAside`, tipos e tags. [buscaAjax.js](https://conteudo.cvm.gov.br/system/modules/br.com.squadra.principal/resources/js/buscaAjax.js) respondeu 200: L67–110 mostram a seleção de página; L23–35 mostram POST e substituição de fragmentos HTML. [populateResults.js](https://conteudo.cvm.gov.br/system/modules/br.com.squadra.principal/resources/js/populateResults.js) respondeu 200 e extrai `article`/`.paginacao` de HTML; [loadAside.js](https://conteudo.cvm.gov.br/system/modules/br.com.squadra.principal/resources/js/loadAside.js), também 200, preenche filtros.

Uma tentativa direta GET e outra POST nesse JSP, com parâmetros reconstruídos, retornaram 200 **sem os títulos esperados**. Portanto, o contrato do endpoint isolado continua **UNVERIFIED**; não foi chamado de API funcional com base no status. O GET paginado do próprio índice já funcionou e é a alternativa demonstrada. O JSP é mecanismo interno do site, sem estabilidade contratual/SLA confirmados.

## 4. Página da norma, íntegra e anexos

| Página requisitada — todas 200 | O que realmente foi observado |
|---|---|
| [Resolução 175](https://conteudo.cvm.gov.br/legislacao/resolucoes/resol175.html) | `h2`, data, ementa, publicação/retificação, tabela de downloads, original PDF, consolidado PDF/DOCX, parte geral, 12 anexos normativos e suplementos. Relação textual com links para resoluções alteradoras |
| [Resolução 249](https://conteudo.cvm.gov.br/legislacao/resolucoes/resol249.html) | Ementa/data e links separados **HTML, PDF e DOCX**. A página de metadados não é o HTML da íntegra |
| [Instrução 400](https://conteudo.cvm.gov.br/legislacao/instrucoes/inst400.html) | Título com “Revogada”, original, consolidado, versão sem marcas em DOC, lista de alterações, revogação parcial e referência à Resolução 160/2022 como revogadora |
| [Parecer 40](https://conteudo.cvm.gov.br/legislacao/pareceres-orientacao/pare040.html) | Título/data e downloads PDF e DOCX; não foi observado link de íntegra HTML nesse bloco |
| [Ofício Anual SEP 2024](https://conteudo.cvm.gov.br/legislacao/oficios-circulares/sep/oc-anual-sep-2024.html) | Metadados e link PDF da íntegra |
| [Deliberação 907](https://conteudo.cvm.gov.br/legislacao/deliberacoes/deli0900/deli907.html) | Links para íntegra HTML, PDF e DOCX em `/anexos/0900/deli907site.*` |

O texto da Resolução 249 foi efetivamente obtido em [resol249.htm](https://conteudo.cvm.gov.br/legislacao/resolucoes/anexos/200/resol249.htm): **200, `text/html;charset=UTF-8`, 39.566 bytes**, com capítulos e dispositivos. O HTML permite extração textual. A conversão foi testada depois, na rodada 2; ver `pdf-para-md.md`.

Também foram baixados em memória dois PDFs, ambos com conteúdo identificado por `%PDF-1.7`:

| Recurso real | HTTP / tamanho | SHA-256 dos bytes recebidos |
|---|---|---|
| [Resolução 249 original](https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/200/resol249.pdf) | 200, `application/pdf`, **342.863 bytes** | `24eb8b5a0808c547b8ca78c80b6c79d95509a8dbef63334715e08a642d3f71ef` |
| [Resolução 175 consolidada](https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/100/resol175consolid.pdf) | 200, `application/pdf`, **3.259.373 bytes** | `8921f2352cd918c7640463bebe94a87cbe474774e7ba5bd7a3d1155d1b3d3db8` |

Na Fase 0 não houve extração/OCR desses PDFs nem inspeção visual de páginas. O benchmark posterior está em `pdf-para-md.md`; as limitações abaixo descrevem aquela fase inicial. Camada textual, equivalência integral entre HTML/PDF/DOCX e qualidade das tabelas: **UNVERIFIED**. URLs de anexos diferentes não devem ser fundidas com a norma principal nem contadas como normas adicionais.

## 5. Metadados: o que se pode e o que não se pode afirmar

| Campo | Evidência | Tratamento recomendado |
|---|---|---|
| Tipo, número e título | Texto do título e caminho | Preservar título original e identidade normalizada separadamente |
| Data do ato | Data em listagem/página e epígrafe da íntegra | Separar assinatura, publicação, captura e futura produção de efeitos |
| Ementa | Parágrafos HTML, por vezes com links e quebras | Guardar texto e HTML de origem; não usar regex que elimine remissões |
| Publicação/retificação | Notas textuais sobre DOU | Não assumir campo estruturado universal; conservar a evidência literal |
| Revogação | Título e nota explícita na Instrução 400 | Situação desconhecida quando não houver evidência; ausência de “revogada” não prova vigência |
| Alteradoras | Bloco textual com links na Resolução 175 | Extrair relações com URL e contexto; lista não foi certificada como exaustiva |
| Anexos e variantes | Downloads/tabelas e parágrafos | Registrar rótulo, MIME, URL e hash por artefato; distinguir original, consolidado, sem marcas e suplemento |
| Assuntos | Tags e lista temática | Úteis para busca; classificação editorial não prova aplicabilidade a uma carteira |
| Vigência e eficácia por dispositivo | Dependem de texto, alterações e transições | **UNVERIFIED** como informação universal estruturada; não sintetizar booleano |

Há um motivo concreto para reconciliar relações: a página inicial de resoluções anuncia a 247 como alteradora da 175, mas o bloco de alterações da página 175 recebido terminava na 240/26. Esta é **uma divergência observada entre páginas**, não conclusão sobre o conteúdo do PDF ou sobre quais dispositivos estão vigentes. O futuro coletor deve preservar ambos os registros e encaminhar a inconsistência para revisão.

## 6. RSS, API e dados abertos

[A lista de feeds](https://conteudo.cvm.gov.br/feed.html) respondeu **200** e aponta legislação, decisões, audiências e outros canais. [O RSS de legislação](https://conteudo.cvm.gov.br/feed/legislacao.xml) respondeu **200, `text/xml;charset=UTF-8`, 8.901 bytes**, contendo **10 itens** com `title`, `link`, `description` e `pubDate`.

O primeiro item recebido era a **Resolução 67/2022**, com `pubDate` em **16/10/2026**, e descrição mencionando alteração pela 248/26. Portanto, **RSS sinaliza também atualização de página antiga**; sua data não é automaticamente a data de criação de uma norma. Os links usam o host legado `http://www.cvm.gov.br`; a identidade deve preservar a URL original e registrar a URL canônica efetivamente acessada. O feed curto não recupera sozinho o histórico e pode perder eventos entre consultas; entrega garantida e retenção: **UNVERIFIED**.

O [Portal Dados Abertos CVM](https://dados.cvm.gov.br/) respondeu 200 e identifica CKAN. Foram feitas duas consultas públicas pontuais antes da leitura de robots:

| Requisição | Resultado |
|---|---|
| `GET https://dados.cvm.gov.br/api/3/action/package_search?q=resolucoes` | **200**, JSON, `success=true`, `count=0` |
| `GET https://dados.cvm.gov.br/api/3/action/package_list` | **200**, JSON, `success=true`, **54 identificadores** de conjuntos |

Entre os identificadores reais estão `cia_aberta-doc-dfp`, `cia_aberta-doc-itr`, `cia_aberta-cad`, `ato_declr-intermed` e `processo-sancionador`. **Não apareceu conjunto dedicado à íntegra de resoluções/instruções no rol recebido.** Isso confirma uma API CKAN de catálogo; não comprova API de corpus normativo, inexistência absoluta de outro serviço ou exportação integral de normas. Uma API oficial documentada, estável e completa para esse corpus permanece **UNVERIFIED**.

Após a descoberta de `Disallow: /api/` no robots desse host, não foi feita varredura adicional da API. HTTP público acessível e autorização para crawling são avaliações distintas. Para o projeto, preferir listagens/feeds demonstrados e confirmar a política antes de automatizar o acesso à API CKAN.

## 7. Robots, termos e licença por contexto

Os três arquivos robots responderam **200**:

| Fonte | Regras observadas e consequência |
|---|---|
| [conteudo.cvm.gov.br/robots.txt](https://conteudo.cvm.gov.br/robots.txt) | Proíbe `/apoio`, `/jornalistas`, `/teste` e URLs específicas. Inclui `/legislacao/deliberacoes/deli0200/deli233.html` e o diretório de anexos `/export/sites/cvm/legislacao/deliberacoes/anexos/0200/noindex`, além de dois PDFs de decisões. Não há proibição geral a `/legislacao/` nem `Crawl-delay` nesse arquivo |
| [www.gov.br/robots.txt](https://www.gov.br/robots.txt) | Regras globais e numerosas restrições específicas a outros órgãos; não foi observada proibição geral à página CVM examinada |
| [dados.cvm.gov.br/robots.txt](https://dados.cvm.gov.br/robots.txt) | Proíbe `/dataset/rate/`, `/revision/`, `/dataset/*/history` e **`/api/`**; declara **`Crawl-Delay: 10`** |

Respeitar as exclusões específicas; não contornar bloqueios ou reintroduzir arquivos desindexados por outro caminho. Capacidade numérica/SLA do portal de conteúdo: **UNVERIFIED**; o delay 10 pertence ao host de dados, não deve ser atribuído como regra publicada do host de legislação. Como recomendação operacional futura, usar fila conservadora, identificação honesta, cache e recuo em erro, sem declarar uma taxa “permitida” não documentada.

A página gov.br de normas publica no rodapé, HTML L5887, a licença **Creative Commons Atribuição-SemDerivações 3.0 Não Adaptada**, com [link oficial à CC BY-ND 3.0](https://creativecommons.org/licenses/by-nd/3.0/deed.pt_BR). O resumo oficial permite compartilhamento inclusive comercial sob condições e restringe a distribuição de adaptações. **Isso é o aviso daquela página/portal; não prova a licença de cada anexo em outro domínio.** A própria licença ressalva materiais em domínio público e exceções legais.

Os [termos de dados.cvm.gov.br](https://dados.cvm.gov.br/about), requisitados com **200**, especificam acesso gratuito a pessoas físicas/jurídicas, fornecimento sem garantia de continuidade/tempestividade, possibilidade de limitar acessos simultâneos e atribuição da origem no uso secundário; mandam verificar a licença de cada conjunto. **ODbL dos conjuntos contábeis não se transfere por associação aos HTML/PDF de legislação.** Uma licença ODbL para o corpus normativo não foi encontrada nesta pesquisa.

Nas páginas de conteúdo examinadas não foi localizado aviso específico de licença aplicável a toda a coleção de normas, nem termos próprios de scraping. **Termos gerais adicionais e sua aplicabilidade a todas as variantes: UNVERIFIED.** Não interpretar a ausência de aviso como atribuição de licença MIT, ODbL ou CC0.

Há uma base jurídica distinta: a [Lei 9.610/1998, art. 8º, IV](https://www.planalto.gov.br/ccivil_03/leis/l9610.htm) exclui os textos de atos oficiais da proteção autoral que ela disciplina. A consulta direta pelo Python ao Planalto sofreu timeout de 25 s; a página oficial foi obtida pelo navegador de pesquisa e o dispositivo foi lido. Isso sustenta tratar o **texto normativo oficial** separadamente de material editorial, software, imagens e conteúdo de terceiros. O enquadramento de cada anexo externo, comentário ou compilação é **UNVERIFIED**, e não se deve ignorar direitos eventualmente próprios desses materiais. Esta é pesquisa documental, sem aprovação jurídica do futuro produto.

## 8. Anexo — pequenos trechos reais de HTML

São excertos literais do HTML recebido; os intervalos servem à localização e não afirmam que o trecho entre eles foi reproduzido integralmente.

**Listagem de resoluções**, `/legislacao/resolucoes.html`, L1458 e L1488–1491:

```html
<form id="pesqAvancada" action="/legislacao/index.html" class="form-horizontal labelLeft no-padding col-sm-12" role="form">
<input type="hidden" value="resolucoes" name="pasta"/>
<input type="hidden" value="/legislacao/resolucoes/" name="vimDaCategoria"/>
```

**Busca de resoluções**, URL parametrizada da seção 3, L1644 e L2398–2399:

```html
<span>249 resultados encontrados</span>
<input type="hidden" name="max" value="25" />
<li><span>Páginas 1/25</span></li>
```

**Página da Resolução 249**, `/legislacao/resolucoes/resol249.html`, L1428 e fragmento do link em L1446:

```html
<h2>Resolução CVM 249</h2>
<a href="/legislacao/resolucoes/anexos/200/resol249.htm">[HTML]</a>
```

**Página da Instrução 400**, `/legislacao/instrucoes/inst400.html`, L1430 e L1522:

```html
<h2>Instrução CVM 400 (Revogada)</h2>
<p><strong>REVOGADA</strong> pela Resolução <a href="/legislacao/resolucoes/resol160.html" target="_blank">160/22</a>.</p>
```

**Anexo da Resolução 175**, `/legislacao/resolucoes/resol175.html`, L1513:

```html
<li><a href="/export/sites/cvm/legislacao/resolucoes/anexos/100/resol175consolid_Anexo03.pdf" target="_blank">Anexo Normativo III &ndash; Fundos de Investimento Imobiliário</a></li>
```

## 9. Direção recomendada para a próxima fase

Usar **catálogo CVM como inventário**, páginas individuais como metadados/relações e arquivos vinculados como íntegra; priorizar HTML quando existir, manter PDF original/consolidado e anexos como evidência. RSS é sinal incremental, acompanhado de reconciliação periódica do catálogo e de hashes de recursos já conhecidos. O DOU pode confirmar a publicação original, sem substituir consolidados e orientações da CVM.

Antes de declarar o corpus completo ou apto a citação automática: deduplicar identidades, revisar anexos, medir falhas e conversão, confirmar limites operacionais e documentar direitos por classe de artefato. Permanecem **UNVERIFIED** a cobertura integral, execução periódica, vigência por dispositivo, extração dos PDFs e existência de API normativa oficial completa. Nenhum desses pontos foi preenchido por estimativa.
