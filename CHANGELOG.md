# Histórico de versões

## 1.0.0 (10/11/2026): primeira versão pública

**Acervo** (`acervo/`)

- Atos normativos da CVM em Markdown, um arquivo por norma, com cabeçalho YAML: identificação, datas, situação normativa com a fonte que a sustenta, relações entre normas, versão do texto, qualidade da conversão e origem (URL e SHA-256 do arquivo oficial).
- Todas as resoluções, pareceres de orientação e ofícios-circulares; os demais atos vigentes das outras espécies; audiências públicas (edital e relatório) das normas que lhes deram origem.
- Justificativas de dispensa de Análise de Impacto Regulatório (AIR) citadas nas fichas das normas, com o texto convertido.
- Versão consolidada das normas alteradas, com a redação original ao lado.
- Índices por espécie e tabela de vigentes, revogados e cobertura em relação ao catálogo oficial da CVM, atualizados automaticamente.

**Programa**

- Coleta educada pelo catálogo oficial da CVM, com auditoria de cada requisição e retomada.
- Banco SQLite com a evidência de cada metadado e busca FTS5; originais imutáveis por SHA-256.
- Conversão de HTML, DOCX e PDF com conferência de fidelidade, decodificação de fontes Type3 e OCR.
- Consolidação derivada do consolidado oficial e gerada pelo motor de alterações, marcada como não oficial.
- Interface local de pesquisa, exportação para Word, PDF, Markdown e texto, atualização incremental.
- Comando `publicar-acervo`, que gera a pasta `acervo/` de forma determinística.
- Windows, Linux e macOS.

**Licenças:** código sob GNU AGPL v3, com termo de preservação dos créditos (`NOTICE`); acervo sob CC BY 4.0.
