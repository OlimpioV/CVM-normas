# Formato dos arquivos do acervo

A pasta `acervo/` é gerada pelo comando `repositorio-cvm publicar-acervo <pasta>` a partir do banco do acervo. Não a edite à mão: correções devem ir para o código ou para os dados de origem (veja `CONTRIBUTING.md`).

A geração é determinística: a mesma base produz os mesmos arquivos, e o histórico do Git mostra só o que mudou de fato numa atualização.

## Caminhos

| Conteúdo | Caminho |
|---|---|
| Norma (versão principal) | `acervo/<espécie>/<ano>/<id>.md` |
| Redação original de norma alterada | `acervo/<espécie>/<ano>/<id>.original.md` |
| Audiência pública | `acervo/audiencias-publicas/<ano>/<id>.md` |
| Justificativa de dispensa de AIR | `acervo/justificativas-air/<ano>/<id da norma>.md` |
| Índice de uma espécie | `acervo/<espécie>/README.md` |
| Índice geral e cobertura | `acervo/README.md`, `acervo/cobertura.csv`, `COBERTURA.md` |

Pastas de espécie: `resolucoes`, `instrucoes`, `deliberacoes`, `pareceres-de-orientacao`, `oficios-circulares` e `notas-explicativas`. O ano é o da edição do ato (`sem-ano` quando a fonte não o informa).

O `id` é estável e legível: `resolucao-cvm-175`, `deliberacao-cvm-906`, `parecer-orientacao-cvm-1`, `oficio-circular-cvm-sep-01-2018`.

## Versão principal

- **Norma sem alterações:** a redação original.
- **Norma alterada:** a versão **consolidada**, só com o texto vigente. As notas de alteração ficam ao lado de cada dispositivo alterado. Ela pode ser de dois tipos, e o campo `versao_aviso` diz qual:
  - **derivada do consolidado oficial da CVM:** a redação anterior, que vem tachada no arquivo oficial, é retirada;
  - **gerada automaticamente, não oficial:** usada quando a CVM ainda não incorporou alguma alteração ao consolidado. O sistema aplica as alterações a partir do texto das normas alteradoras, e o campo `qualidade` diz quantas foram aplicadas.

Só entram versões **aprovadas** na conferência de fidelidade. Uma conversão reprovada não é publicada, e a norma aparece no índice como "não localizado", com link para a ficha oficial.

## Cabeçalho das normas

| Campo | Conteúdo |
|---|---|
| `id` | identificador do ato no acervo |
| `titulo`, `especie`, `numero`, `ano` | identificação, como na ficha oficial |
| `ementa` | ementa oficial |
| `data_edicao`, `data_publicacao_dou` | datas (AAAA-MM-DD); `null` quando a fonte não as informa |
| `inicio_vigencia`, `fim_vigencia` | quando há evidência (cláusula de vigência ou ficha) |
| `situacao` | `vigente`, `vigente com alterações`, `vigência futura`, `integralmente revogada` ou `não verificado` |
| `situacao_fonte` | URL de onde a situação foi tirada |
| `situacao_verificada_em` | data da última leitura da ficha |
| `ficha_oficial` | página do ato no portal da CVM |
| `versao`, `versao_aviso` | qual texto é este e como foi obtido |
| `fonte` | URL do arquivo oficial convertido (HTML, DOCX ou PDF) |
| `fonte_sha256` | SHA-256 dos bytes baixados: permite conferir se o arquivo oficial mudou |
| `fonte_coletada_em` | data do download |
| `conversor` | conversor e versão usados |
| `qualidade` | `alta`, `média` ou `baixa`, com o motivo |
| `relacoes` | lista de `tipo` (`altera`, `alterada_por`, `revoga`, `revogada_por`, `vide`), `norma` (id no acervo ou URL) e `evidencia` (URL onde a relação aparece) |
| `audiencias_publicas` | ids das audiências que deram origem ao ato |
| `justificativa_air` | caminho (relativo a `acervo/`) da justificativa de dispensa de Análise de Impacto Regulatório citada na ficha; `null` se a ficha não cita nenhuma |
| `aviso_vigencia`, `aviso` | avisos de uso |

### Qualidade

- **alta:** a conversão confere com outra fonte do mesmo ato (por exemplo, DOCX × PDF) ou veio de HTML estruturado;
- **média:** texto extraído de PDF com camada de texto, sem segunda fonte para conferir, ou consolidação gerada automaticamente;
- **baixa:** OCR. Erros típicos aparecem em e-mails, siglas e tabelas. Confira com o original antes de citar.

## Corpo

O corpo é Markdown comum. Algumas convenções preservam o texto oficial:

- cada dispositivo (artigo, parágrafo, inciso, alínea) é um bloco separado por linha em branco;
- numeração e marcadores são **texto**, não listas Markdown, e nunca são renumerados;
- tabelas complexas (células mescladas) vêm em HTML;
- a redação anterior tachada, nas versões com tachado, aparece como `~~texto~~`;
- notas de rodapé usam `[^n]`, com o número do original;
- o caractere `□` marca um caractere que não pôde ser identificado no PDF (inclusive caracteres de controle vindos de fontes sem mapeamento Unicode).

## Audiências públicas

Cabeçalho com `codigo`, `tema`, `fase`, `prazo`, `prazo_no_edital`, `pagina_oficial`, `normas` e a lista `arquivos`. Cada arquivo traz seção, rótulo, URL, SHA-256, data da coleta e se foi convertido. O corpo traz o texto convertido do edital e do relatório. As manifestações recebidas não são coletadas.

## Justificativas de dispensa de AIR

Quando a ficha oficial da norma cita uma "Justificativa - Dispensa de Análise de Impacto Regulatório (AIR)", o documento é baixado e convertido. Ele pode ser um PDF anexo ou a página da decisão do Colegiado que aprovou a norma; neste caso, o texto é o da decisão. O cabeçalho traz `norma`, `ficha_oficial` e a lista `documentos`, cada um com rótulo, URL, SHA-256, data da coleta, qualidade e a ficha que o cita. A ficha sem esse link não prova que não houve justificativa.
