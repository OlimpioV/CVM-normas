> Pesquisa inicial sobre as fontes, feita em 21 a 27/10/2026. Insumo de pesquisa: conclusões a reconferir nas fontes oficiais antes de serem adotadas.

# Inventário do acervo CVM (rodada 4)

Consolidação das frentes de inventário executadas em 21–22/10/2026 por requisições HTTP reais aos hosts `conteudo.cvm.gov.br` e `www.gov.br/cvm`, com User-Agent identificado, uma requisição por vez por frente (intervalo ≥ 5 s) e respeito ao `robots.txt`. Nenhum acesso a `dados.cvm.gov.br/api`. Os corpos HTTP, scripts e relatórios integrais de cada frente são evidência local não versionada.

Escopo aplicado: decisões D-U6 a D-U11 em [decisoes-usuario.md](decisoes-usuario.md). As cinco famílias originais vêm de [fontes-cvm.md](fontes-cvm.md) e [reconferencia.md](reconferencia.md).

## 1. Tabela final

| Classe | Categoria | Registros | Método | Anos | Formatos |
|---|---|---:|---|---|---|
| **norma** | Resoluções | 249 | contador da busca, reconferido | 2020–2026 | HTML + PDF + DOCX |
| **norma** | Instruções | 627 | contador da busca, reconferido | **1978–2020** | PDF/DOC, consolidados |
| **norma** | Deliberações | 907 | contador da busca, reconferido | **1978–2026** | HTML + PDF + DOCX |
| **norma** | Pareceres de Orientação | 41 | contador da busca, reconferido | — | PDF + DOCX |
| **norma** | Decisões conjuntas | 34 | enumeração da pasta | **1990–2024** | HTML + PDF |
| **norma** | Portarias normativas (D-U9) | 5 + 2 em revisão | ementa das 65 portarias listadas | 2001–2026 | PDF |
| **orientação** | Ofícios circulares | 600 | contador da busca, reconferido | — | HTML + PDF/DOCX |
| **orientação** | Notas explicativas | 77 | busca por categoria (confirmado por duas frentes) | 1977–2022 | HTML + anexo |
| **orientação** | Perguntas e respostas | 23 + 18 + 50 | contagem de blocos nas páginas | — | HTML |
| **orientação** | Manuais e guias | ≥ 11 | requisição de 11 de 31 candidatos | 2016–2025 | PDF, HTML |
| **minuta** | Audiências e consultas públicas (D-U7, D-U10) | 342 | enumeração integral (7 × 50) | 2004–2026 | HTML + PDF/DOC |
| | **Total no escopo** | **≈ 2.990** | | | |

Contagens de catálogo, não censo deduplicado de normas vigentes. Ofícios circulares ficam como orientação por padrão, com marcação explícita quando forem determinação.

Faixas de anos em negrito foram reconfirmadas por enumeração integral do catálogo com ordenação cronológica, sem inversões de data, e conferidas por duas capturas independentes do mesmo catálogo. As faixas sem destaque (resoluções, pareceres de orientação, ofícios circulares, perguntas e respostas) **permanecem UNVERIFIED**: a enumeração desses grupos não foi percorrida ato a ato para extrair a data, e o intervalo mostrado é o que o inventário anterior registrava.

## 2. Fora do escopo

| Categoria | Registros | Motivo |
|---|---:|---|
| Portarias administrativas | 58 | RH, TI, orçamento, comitês (D-U9) |
| Portarias conjuntas | 2 | criam grupos de trabalho |
| Leis e decretos | 5 | legislação federal (D-U8) |
| Pronunciamentos CPC/ICPC/OCPC | 8 OCPC + CPC/ICPC | fase 2 (D-U11); a resolução de aprovação entra |
| Manifestações em audiências | — | só link para a página oficial (D-U10) |
| Atos declaratórios | total UNVERIFIED | sistema externo, autorizações individuais |
| Decisões do Colegiado, sancionadores | — | jurisprudência (D-U8) |

## 3. Fontes de descoberta

| Fonte | Uso | Achado |
|---|---|---|
| Busca `legislacao/index.html?...&vimDaCategoria=/legislacao/<familia>/` | **catálogo primário** | contadores estáveis entre rodadas |
| `resultadoAudienciaPublica.jsp` (POST) | catálogo de minutas | aceita 50 itens por página; contador oscilou 342/343 |
| Sitemap `conteudo.cvm.gov.br/sitemap.xml` | mapa de anexos | 55.105 URLs, 7.752 sob `/legislacao/`; `lastmod` 2026-06-09, sem itens recentes |
| Sitemap `www.gov.br/cvm` | nenhum | 200 URLs, todas notícias |
| Hub `www.gov.br/cvm/pt-br/assuntos/normas` | navegação | 11 links, 7 redirecionam para o portal de conteúdo |
| RSS (6 canais em `feed.html`) | sinal incremental | 10 itens por canal; data do item não é data da norma |
| Portaria 123/2022 | índice de vigência | 210 atos vigentes com corte em 01/08/2022 |
| Planilha de revisão/consolidação | índice de relações | cobre 2020–2023; página parada desde 02/04/2024 |

## 4. Camada de texto e OCR

- Os três PDFs do benchmark e as amostras antigas das categorias novas têm texto extraível.
- **Primeiro caso sem texto:** Portaria 109/2020, 6 páginas só com desenho vetorial. Precisará de OCR ou extração alternativa. Cobertura raster baixa **não** exclui conteúdo sem texto: esse arquivo tem muito vetor e zero caracteres extraíveis.
- **Amostragem por década de instruções e deliberações antigas (concluída):** 78 arquivos PDF e 676 páginas, com **zero páginas sem camada textual** por **dois extratores independentes** (uma biblioteca de leitura de PDF e um motor de documento com ligação ao renderizador). Caracteres por página: mínimo **113**, mediana **2144**, máximo **3899** no primeiro extrator; mínimo **112**, mediana **2146**, máximo **3889** no segundo. Cobertura raster por página: máximo **4,4%** em toda a amostra (logotipo/selo de cabeçalho), nenhuma página com cobertura raster igual ou superior a 50%.
  - **Limite da amostragem:** a seleção foi **determinística e equiespaçada** (5 atos por década e por família, mais 2 documentos complementares fora dela), **não probabilística**. Os limites nominais calculados — 3,77% por documento (n=78) e 0,44% por página (n=676) — são referência aritmética condicionada, **não** intervalos de confiança do acervo; e as páginas de um mesmo documento são correlacionadas, de modo que o documento é a unidade primária. Os 78 arquivos medidos são 4,5% dos 1.718 apontados pelo mapa de anexos para essas duas famílias. **Não se afirma ausência de OCR para famílias inteiras.**
  - **Consequência operacional:** o gatilho de OCR é a **ausência de camada textual**, não o limiar exploratório de "menos de 50 caracteres" — as páginas mais esparsas da amostra são folhas de assinatura e formulários com texto real entre 112 e 200 caracteres, e vão para revisão de fidelidade, não para OCR. A variante de nome do PDF do próprio ato é descoberta pelos links oficiais da página do ato, não presumida pelo nome.
  - **Continua UNVERIFIED:** distribuição de PDFs sem texto no universo completo das famílias, anexos normativos, versões "sem marcas" e artefatos fora da nomenclatura do próprio ato; e qualidade de OCR, que não foi executada.
- **OCR não é dispensado** no caminho de conversão; ver a decisão D-10 em `../research.md`.

## 5. Divergências registradas

1. Contador de audiências oscila entre 342 e 343 em requisições idênticas; a enumeração fecha 342.
2. A página da Resolução 175 lista alterações até a 240/26, enquanto o portal anuncia a 247 como alteradora.
3. Sitemaps parados: portarias 139, 176 e 177/2026 e consultas de 2026 não aparecem neles.
4. Ofícios SNC/SSE têm link duplicado na listagem (risco de contagem dupla).
5. Seis URLs antigas consultadas responderam 410; o diretório `inst2` tem 5 URLs, todas 410.
6. Algumas URLs de anexos devolvem página HTML com status 200 no lugar do PDF (soft-404).
7. O PDF do próprio ato nem sempre segue a nomenclatura esperada: a página de uma deliberação recente de 2026 oferece o PDF sob nome com sufixo próprio, e não sob o número do ato. Um seletor restrito a um único padrão de nome produziu falso negativo ("ato sem PDF"). A variante é descoberta pelos links oficiais e validada pela identidade do ato.
8. A enumeração dos ofícios circulares retornou 599 em uma frente de pesquisa e 600 nas contagens reconferidas; as 599 URLs distintas foram preservadas e a causa da diferença é **UNVERIFIED**. O valor 600 da tabela da seção 1 é o reconferido.
9. As faixas de anos de instruções (1978–2020) e deliberações (1978–2026) corrigem o registro anterior, que indicava 1977–2022 e 1977–2026; as datas vêm do campo de data do catálogo, com ordenação cronológica sem inversões.

## 6. UNVERIFIED

- Total real de portarias da CVM (87 números distintos observados) e classificação das 65 pelo texto integral, não só pela ementa.
- Total de manuais e guias (11 de 31 candidatos requisitados) e de documentos de refazimento por ano.
- Faixa de anos de pareceres, ofícios e perguntas e respostas.
- Contrato e estabilidade dos endpoints internos de busca (`*.jsp`).
- Cobertura de URLs fora do menu, da busca e dos sitemaps.
- Lista oficial de atos vigentes posterior à Portaria 123/2022.
- Licença de cada anexo fora da página gov.br que exibe CC BY-ND 3.0.
- Causa da diferença entre 599 e 600 no catálogo de ofícios circulares; o valor 600 é o reconferido.
- Proporção de PDFs sem camada textual no universo completo das famílias de instruções e deliberações: a amostragem por década mediu 78 arquivos e 676 páginas sem nenhum caso, mas é determinística e não probabilística e cobre 4,5% dos arquivos apontados para essas famílias. Qualidade de OCR não foi medida, porque não foi executada.
- Enumeração ato a ato das faixas de anos de resoluções, pareceres de orientação, ofícios circulares e perguntas e respostas: os intervalos registrados na tabela da seção 1 não foram reconfirmados para esses grupos.
