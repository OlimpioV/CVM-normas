# Repositório Normativo CVM

[![testes](https://github.com/OlimpioV/CVM-normas/actions/workflows/testes.yml/badge.svg)](https://github.com/OlimpioV/CVM-normas/actions/workflows/testes.yml)
[![código: AGPL v3](https://img.shields.io/badge/c%C3%B3digo-AGPL%20v3-blue)](LICENSE)
[![acervo: CC BY 4.0](https://img.shields.io/badge/acervo-CC%20BY%204.0-green)](LICENSE-ACERVO)

O acervo normativo da **Comissão de Valores Mobiliários (CVM)** em Markdown: resoluções, instruções, deliberações, pareceres de orientação, ofícios-circulares, notas explicativas e audiências públicas. Junto vai o programa que o coleta, confere, consolida e atualiza a partir das fontes oficiais.

Em cada texto há um cabeçalho que diz de onde ele veio: a URL do arquivo oficial, o SHA-256 dos bytes baixados, a data da coleta e a situação normativa com a fonte que a sustenta.

> [!IMPORTANT]
> **Aviso.** Os textos foram convertidos automaticamente dos arquivos oficiais e servem para consulta. Este projeto **não é publicação oficial nem tem vínculo com a CVM**. Antes de citar, confira a fonte indicada no cabeçalho de cada arquivo. Em caso de divergência, prevalece o texto publicado pela CVM. A situação normativa segue as marcações da ficha oficial da CVM. As revogações feitas no texto de outras normas ainda não são cruzadas automaticamente.

## Para que serve

- **Consultar normas no navegador.** Cada espécie tem uma tabela com data, situação e ementa, e cada norma abre direto no GitHub, com a fonte oficial no cabeçalho.
- **Base de conhecimento para IA (RAG).** Assistentes e agentes podem buscar nos arquivos em vez de responder de memória. O cabeçalho YAML permite filtrar por espécie, situação ou data, e cada trecho recuperado leva junto a URL oficial para citar.
- **Análise e pesquisa.** Contar normas por ano e espécie, mapear quem altera ou revoga quem (campo `relacoes`), medir a produção normativa, comparar redações.
- **Acompanhar mudanças.** O acervo é gerado de forma determinística: numa atualização, o histórico do Git mostra exatamente o que mudou em cada norma. Dá para seguir pelo botão **Watch** do GitHub ou por `git diff`.
- **Ferramentas de compliance.** Checklists, alertas de vigência e buscadores internos podem usar os arquivos e os metadados como fonte, sem raspar o site da CVM de novo.
- **Treinar ou avaliar modelos de linguagem** com texto normativo em português, com origem rastreável (veja [Licença e créditos](#licença-e-créditos)).

## O acervo

<!-- tabela-acervo:inicio (gerada pelo publicar-acervo; não edite à mão) -->
Posição em 06/11/2026 (última verificação nas fontes oficiais). Tabela atualizada automaticamente pelo `publicar-acervo`.

| Espécie | No acervo (vigentes) | No acervo (revogados) | Na CVM (vigentes) | Na CVM (revogados) | Cobertura total | Cobertura vigentes |
|---|---:|---:|---:|---:|---:|---:|
| [Resoluções](acervo/resolucoes/README.md) | 231 | 18 | 231 | 18 | 100% | 100% |
| [Instruções](acervo/instrucoes/README.md) | 8 | 20 | 8 | 619 | 4,5% | 100% |
| [Deliberações](acervo/deliberacoes/README.md) | 480 | 11 | 481 | 426 | 54,1% | 99,8% |
| [Pareceres de Orientação](acervo/pareceres-de-orientacao/README.md) | 41 | 0 | 41 | 0 | 100% | 100% |
| [Ofícios-Circulares](acervo/oficios-circulares/README.md) | 600 | 0 | 600 | 0 | 100% | 100% |
| [Notas Explicativas](acervo/notas-explicativas/README.md) | 6 | 70 | 6 | 71 | 98,7% | 100% |
| **Total** | **1.366** | **119** | **1.367** | **1.134** | **59,4%** | **99,9%** |

Vigentes inclui os atos vigentes com alterações e os já publicados com vigência futura; revogados são os integralmente revogados. No acervo, a situação é a da ficha oficial de cada ato. Na CVM, os atos que estão no acervo seguem a ficha oficial e os ainda não coletados seguem a marca "(Revogada)" do catálogo da CVM, que é incompleta: esses números podem mudar quando forem coletados.

Mais 8 [audiências públicas](acervo/audiencias-publicas/README.md) (edital e relatório) das normas que lhes deram origem.

Mais 68 [justificativas de dispensa de Análise de Impacto Regulatório](acervo/justificativas-air/README.md) citadas nas fichas das normas.
<!-- tabela-acervo:fim -->

A cobertura é medida contra o **catálogo oficial da CVM**, lido página por página. O que falta está listado em [`COBERTURA.md`](COBERTURA.md). A coleta histórica começou pelos atos vigentes; os que faltam são, sobretudo, instruções e deliberações revogadas (veja [O que ainda falta](#o-que-ainda-falta)).

### Estrutura

```
acervo/
├── README.md                     índice geral
├── cobertura.csv                 cobertura por espécie e ano
├── resolucoes/
│   ├── README.md                 tabela de todas as resoluções: data, situação, ementa, link
│   └── 2022/
│       ├── resolucao-cvm-175.md            texto consolidado (só o texto vigente)
│       └── resolucao-cvm-175.original.md   redação original
├── instrucoes/ · deliberacoes/ · pareceres-de-orientacao/
├── oficios-circulares/ · notas-explicativas/
├── audiencias-publicas/2020/sdm-2020-sdm0820.md
└── justificativas-air/2025/resolucao-cvm-233.md     justificativa de dispensa de AIR
```

Em cada norma, o arquivo principal traz a **versão consolidada** (só o texto vigente) quando a norma foi alterada, e a redação original quando não foi. Nas normas alteradas, a redação original fica ao lado, em `*.original.md`.

### Formato dos arquivos

```yaml
---
id: "resolucao-cvm-175"
titulo: "Resolução CVM 175"
especie: "Resolução"
numero: "175"
ano: 2022
ementa: "Dispõe sobre a constituição, o funcionamento e a divulgação de informações dos fundos de investimento, ..."
data_edicao: "2022-12-23"
data_publicacao_dou: "2022-12-28"
inicio_vigencia: "2023-10-02"
situacao: "vigente com alterações"
situacao_fonte: "https://conteudo.cvm.gov.br/legislacao/resolucoes/resol175.html"
ficha_oficial: "https://conteudo.cvm.gov.br/legislacao/resolucoes/resol175.html"
versao: "Consolidada (texto vigente)"
fonte: "https://conteudo.cvm.gov.br/legislacao/resolucoes/anexos/100/resol175consolid.docx"
fonte_sha256: "c1bc7c2bf6fa1a245c3340aaf42fb87422f76f27f08a13387e8971c712986824"
fonte_coletada_em: "2026-10-28"
qualidade: "média: consolidação gerada automaticamente, não oficial, ..."
relacoes:
  - tipo: "alterada_por"
    norma: "resolucao-cvm-181"
    evidencia: "https://conteudo.cvm.gov.br/legislacao/resolucoes/resol175.html"
audiencias_publicas:
  - "sdm-2020-sdm0820"
  - "sdm-2021-sdm0821"
aviso: "Texto convertido automaticamente ... prevalece o original publicado pela CVM."
---
```

A descrição de cada campo e as regras de qualidade estão em [`docs/FORMATO.md`](docs/FORMATO.md).

### Como baixar e ler

Baixe tudo pelo botão **Code → Download ZIP**, ou clone o repositório:

```bash
git clone --depth 1 https://github.com/OlimpioV/CVM-normas.git
```

Ler os metadados de todas as resoluções vigentes em Python (com `pip install pyyaml`):

```python
from pathlib import Path
import yaml

def ler(caminho):
    texto = caminho.read_text(encoding="utf-8")
    _, cabecalho, corpo = texto.split("---\n", 2)
    return yaml.safe_load(cabecalho), corpo

for arquivo in sorted(Path("acervo/resolucoes").rglob("*.md")):
    if arquivo.name == "README.md" or arquivo.name.endswith(".original.md"):
        continue
    meta, corpo = ler(arquivo)
    if meta["situacao"].startswith("vigente"):
        print(meta["titulo"], meta["data_edicao"], meta["fonte"])
```

Num pipeline de RAG, use o corpo como texto e o cabeçalho como metadados de cada trecho. Assim a resposta pode citar `titulo` e `fonte`, e filtrar por `situacao`.

## Por que confiar (e quando não confiar)

- **Nada é inventado.** Cada metadado e cada relação de alteração ou revogação são gravados com a evidência que os sustenta (URL, hash e trecho oficial). Sem evidência, o campo fica nulo ou "não verificado". Um ato que não foi encontrado fica como "não localizado", nunca como "inexistente".
- **Originais imutáveis.** Os arquivos baixados são guardados pelo SHA-256 e nunca são sobrescritos. As conversões ficam em arquivos separados.
- **Conferência de fidelidade.** Uma conversão só entra no acervo se for aprovada na conferência automática: comparação com o texto da fonte, conferência cruzada entre DOCX e PDF e detecção de PDF sem camada de texto. O nível de qualidade (alta, média ou baixa) aparece no cabeçalho. Texto obtido por OCR é sempre "baixa" e exige conferência antes de citar.
- **Consolidação gerada é marcada.** Quando a CVM ainda não publicou o consolidado de uma norma alterada, o sistema aplica as alterações e marca o resultado como **não oficial**, com uma nota em cada dispositivo alterado.
- **Coleta educada.** Respeita o `robots.txt`, se identifica no User-Agent, espera 3 s entre requisições e faz retentativas com espera exponencial. Se o acesso for bloqueado, para em vez de insistir.

## Usar o programa

O programa monta o acervo do zero, mantém o acervo atualizado e oferece uma interface local de pesquisa com exportação para Word e PDF.

### Instalação

Requisitos: Python 3.12 ou mais recente e Git.

**Windows:** clone o repositório e dê duplo clique em `instalar.bat`.

**Linux e macOS:**

```bash
git clone https://github.com/OlimpioV/CVM-normas.git
cd CVM-normas
sh scripts/instalar.sh
```

A instalação cria o ambiente `.venv`, instala as dependências nas versões testadas (`requirements.txt`) e baixa o modelo de português do OCR. Para exportar em PDF no Linux, instale a fonte DejaVu Sans (`apt install fonts-dejavu`).

### Comandos

Todos os comandos rodam como `repositorio-cvm <comando>`, ou `python -m repositorio_cvm <comando>`, com o `.venv` ativado. No Windows também há atalhos em [`scripts/windows/`](scripts/windows/).

| Para… | Comando |
|---|---|
| Ler o catálogo oficial completo da CVM (base da cobertura; ~15 min) | `ler-catalogo` |
| Coletar os atos do catálogo ainda ausentes (retomável) | `coletar-catalogo --familia resolucao` (piloto: `--amostra 20`; só vigentes: `--sem-revogados`) |
| Atualizar: novidades e alterações nas fontes (incremental) | `atualizar` |
| Coletar as normas alteradoras e gerar a versão consolidada | `coletar-alteradoras` e depois `consolidar` |
| Comparar a consolidação gerada com a oficial da CVM | `validar-consolidacao` |
| Coletar as audiências públicas das normas | `coletar-audiencias` |
| Coletar as justificativas de dispensa de Análise de Impacto Regulatório (AIR) citadas nas fichas | `coletar-justificativas` |
| **Pesquisar** por referência ou por palavras | `pesquisar "Resolução CVM 175, artigo 40"` |
| **Abrir a interface de pesquisa** (http://127.0.0.1:8000) | `interface` |
| Exportar uma norma (docx, pdf, md, txt) | `exportar resolucao-cvm-175 docx` (`--versao original`, `--parte anexo-normativo-i`) |
| Gerar o relatório de cobertura | `relatorio-cobertura` |
| Gerar a pasta `acervo/` publicável | `publicar-acervo <pasta>` |
| Organizar os documentos em pastas com nomes legíveis | `organizar` |
| Conferir a integridade dos originais / backup / restaurar | `verificar` · `backup` · `restaurar` |
| Coletar e conferir o gabarito de validação (32 atos) | `coletar --gabarito` · `relatorio-gabarito` |

Os dados ficam em `dados/`, fora do Git: originais por hash, conversões, banco SQLite com busca FTS5, logs com a auditoria de cada requisição, relatórios e backups. Para usar outra pasta, crie um `config.local.toml` com `pasta_dados = "D:/AcervoCVM"`.

### Interface

A interface roda só no seu computador (`127.0.0.1`) e não altera o acervo. Ela oferece:

- pesquisa por referência ("Res 247 art. 5") ou por palavras, com filtros de espécie, situação e período;
- página da norma com metadados e a origem de cada um, relações, arquivos oficiais e três versões nas normas alteradas (consolidada, alterada com a redação anterior tachada e original);
- seleção de partes (Parte Geral, cada Anexo Normativo, Suplementos);
- audiência pública que deu origem à norma;
- relatório de cobertura, com a lista do que falta.

## Como funciona

O caminho completo, da coleta à publicação, está em [`docs/COMO-FUNCIONA.md`](docs/COMO-FUNCIONA.md). As escolhas técnicas e as alternativas descartadas estão em [`docs/DECISOES.md`](docs/DECISOES.md). A pesquisa sobre as fontes da CVM está em [`docs/fontes/`](docs/fontes/).

## O que ainda falta

- **Atos marcados como revogados no catálogo** (cerca de 1.000, quase todos instruções e deliberações): a coleta histórica começou pelos demais.
- **Revogações cruzadas:** a situação vem da ficha de cada ato. Uma revogação declarada só no texto de outra norma ainda não muda a situação automaticamente.
- **Textos obtidos por OCR:** 28 atos só existem como digitalização. O texto deles vem de OCR, com qualidade "baixa" no cabeçalho, e precisa ser conferido com o original antes de citar.
- **Outras fontes:** Diário Oficial da União, atos anteriores ao portal atual da CVM, ofícios das superintendências não listados no catálogo.
- **Atualização automática do acervo público:** hoje o acervo é gerado e publicado à mão, com `atualizar` e depois `publicar-acervo`.

Sugestões e correções são bem-vindas: veja [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Testes

```bash
pip install -e ".[testes]"
python -m pytest
```

Os testes rodam sem rede, usando páginas e arquivos reais da CVM salvos em [`tests/fixtures/`](tests/fixtures/). O **gabarito de validação** ([`tests/gabarito/gabarito.toml`](tests/gabarito/gabarito.toml)) define 32 atos de referência, cujos metadados foram conferidos com as fontes oficiais.

## Licença e créditos

- **Código:** [GNU AGPL v3](LICENSE), com termo adicional que exige preservar os créditos ([`NOTICE`](NOTICE)).
- **Acervo** (organização, metadados, origem, relações, consolidações geradas): [CC BY 4.0](LICENSE-ACERVO).
- **Textos das normas:** atos oficiais, sem proteção autoral (Lei nº 9.610/1998, art. 8º, IV).

Quem reutilizar o código ou o acervo deve dar crédito a este repositório e manter o [`CREDITOS.md`](CREDITOS.md). A organização do acervo em Markdown foi inspirada no **[ctresb/leis](https://github.com/ctresb/leis)**, de João Davi, que reúne a legislação brasileira em Markdown. Fica o reconhecimento, que também deve ser mantido em cópias e derivados.
