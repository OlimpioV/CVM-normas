# Como funciona

O caminho de um ato normativo, do portal da CVM até o arquivo em `acervo/`. As justificativas de cada escolha estão em [`DECISOES.md`](DECISOES.md), referidas aqui como D-nn.

```
catálogo oficial ──► ficha do ato ──► arquivos oficiais ──► originais por hash ──► conversão ──► conferência
  (ler-catalogo)     (metadados,       (HTML, DOCX, PDF)     (imutáveis)            (Markdown)    de fidelidade
                      situação,                                                                     │
                      relações)                                                                     ▼
 acervo/ ◄── publicar-acervo ◄── banco SQLite (metadados + evidências + versões + busca FTS5) ◄── consolidação
```

## 1. Catálogo e cobertura

O comando `ler-catalogo` lê, página por página, a pesquisa de legislação do portal da CVM, para cada espécie. O resultado é a base contra a qual a cobertura é medida (D-16). Ausência no catálogo não prova inexistência: um número que falta na sequência fica como "não localizado".

## 2. Coleta

O cliente HTTP (`coleta/http.py`, D-17) é educado por construção:

- lê o `robots.txt` e o relê em coletas longas. URL proibida é pulada e registrada;
- respeita um intervalo mínimo por servidor (3 s por padrão, piso de 1 s) e o `Crawl-delay`;
- faz retentativas com espera exponencial em erros 5xx e de rede, e respeita o `Retry-After`;
- **para** diante de 401, 403 ou 429, sem tentar contornar;
- confere o formato esperado: uma página de erro no lugar de um PDF vira lacuna, não "original";
- registra cada requisição num log de auditoria (JSONL).

A coleta é retomável: cada ato verificado é registrado, e uma execução interrompida continua de onde parou.

## 3. Ficha, metadados e situação

A ficha de cada ato no portal fornece título, ementa, datas, links para os arquivos e as marcações "ALTERADA pela…" e "REVOGADA pela…". Cada valor é gravado com a **evidência** que o sustenta: URL, SHA-256 da ficha lida e o trecho oficial.

A situação normativa segue uma ordem fixa (D-09): revogação marcada na ficha, vigência futura pela cláusula de vigência, alteração marcada, ausência de marcações, ou "não verificado" quando a ficha não pôde ser lida.

## 4. Originais imutáveis

Os arquivos baixados são guardados em `dados/originais/` pelo SHA-256 dos bytes (D-05, D-10), com o atributo de somente leitura. Um arquivo oficial que muda gera uma nova versão. A anterior é mantida.

## 5. Conversão e conferência de fidelidade

Cada ato é convertido a partir da melhor fonte disponível (D-11): a íntegra em HTML, o DOCX conferido com o PDF, ou o PDF.

- **HTML:** conversão estrutural (`conversao/html.py`), com tabelas em HTML quando têm células mescladas.
- **DOCX:** parágrafos, tabelas, tachado e notas de rodapé (`conversao/docx.py`). É conferido palavra por palavra com o PDF do mesmo ato.
- **PDF:** camada de texto via PyMuPDF (D-03), sem cabeçalho e rodapé. Duas situações têm tratamento próprio:
  - fontes Type3 sem mapeamento Unicode (comuns nos ofícios do SEI) são decifradas pelo desenho dos glifos (`conversao/type3.py`, D-14);
  - quando não há texto legível, entra o OCR com o Tesseract embutido no PyMuPDF (D-12), e o resultado é sempre de qualidade "baixa".

A **conferência de fidelidade** (`conversao/fidelidade.py`) compara as palavras do Markdown com as da fonte. Uma versão reprovada não é exibida nem publicada.

## 6. Versões e consolidação

Uma norma alterada tem até três versões (D-21):

1. **Original:** a redação publicada.
2. **Alterada, com tachado:** o consolidado oficial da CVM, com a redação anterior riscada.
3. **Consolidada:** só o texto vigente, com as notas de alteração. Há dois caminhos para obtê-la:
   - **derivada** do consolidado oficial em DOCX, retirando o tachado;
   - **gerada** pelo motor de alterações (`motor_alteracoes.py`), quando a CVM ainda não consolidou alguma alteração. O motor lê os comandos da norma alteradora ("O art. 5º passa a vigorar com a seguinte redação…") e os aplica. O resultado é marcado como **não oficial**, e `validar-consolidacao` o compara com os consolidados oficiais.

Normas com anexos são divididas em partes, como Parte Geral, Anexos Normativos e Suplementos (D-18). As audiências públicas que deram origem a cada norma são coletadas, com edital e relatório e sem as manifestações (D-19). As justificativas de dispensa de Análise de Impacto Regulatório citadas na ficha também, como documentos próprios ligados à norma (D-24).

## 7. Banco e pesquisa

O SQLite (`dados/acervo.sqlite`, D-02) guarda:

- documentos, evidências, relações e lacunas;
- arquivos, versões de texto e dispositivos (artigo, parágrafo, inciso…);
- o registro de cada coleta.

A busca usa FTS5, sem diferenciar acentos. A pesquisa entende referências como "Resolução CVM 175, artigo 40" e leva direto ao dispositivo.

## 8. Atualização

O comando `atualizar` relê a ficha de cada ato, do verificado há mais tempo para o mais recente. Quando o conteúdo da ficha mudou, o comando:

- guarda a nova ficha;
- atualiza os metadados, com evidência;
- baixa de novo os arquivos de texto;
- registra as diferenças por dispositivo.

A rotina também aponta publicações novas no catálogo. Ela não depende de nenhuma ferramenta de IA.

## 9. Saídas

- **Interface local** (`interface`): FastAPI e Jinja2, só em `127.0.0.1`, somente leitura (D-04, D-15).
- **Exportação** (`exportar`): Word, PDF, Markdown e texto. O cabeçalho traz a identificação, a versão, a fonte e o aviso de vigência. O PDF é conferido palavra por palavra antes de ser entregue.
- **Biblioteca** (`organizar`): pastas com nomes legíveis e vínculos para os originais (D-20).
- **Acervo público** (`publicar-acervo`): a pasta `acervo/` deste repositório. Veja [`FORMATO.md`](FORMATO.md).
