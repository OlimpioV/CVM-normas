# Como contribuir

Correções, sugestões e código são bem-vindos. Antes de tudo, as regras que valem para qualquer contribuição:

## Regras do projeto

- **Fidelidade às fontes.** Nunca invente metadados, números, datas ou situação normativa. Sem evidência, use nulo ou "não verificado". Situação normativa e relações de alteração e revogação exigem evidência documental registrada (URL e trecho oficial).
- **Lacuna não é inexistência.** O que não foi encontrado fica como "não localizado", nunca como "inexistente".
- **Originais imutáveis.** Arquivos baixados nunca são editados nem sobrescritos. As conversões ficam em arquivos separados.
- **Coleta educada.** Respeite o `robots.txt`, o intervalo entre requisições e a identificação no User-Agent. Não contorne CAPTCHA, autenticação ou bloqueio.
- **Sem dados fictícios.** Os testes usam páginas e arquivos reais da CVM, salvos em `tests/fixtures/`. Não declare uma funcionalidade concluída sem teste.
- **Sem dependência de IA ou de serviços pagos** na rotina de coleta e atualização.

## Encontrou um erro no texto de uma norma?

**Não edite os arquivos de `acervo/` à mão.** Eles são gerados pelo comando `publicar-acervo`, e a edição se perderia na próxima geração. Abra uma issue com:

- o arquivo (ex.: `acervo/resolucoes/2022/resolucao-cvm-175.md`) e o trecho;
- o que diz o arquivo oficial da CVM (o link está no campo `fonte` do cabeçalho);
- se possível, a página do PDF ou o dispositivo.

A correção vai para o conversor ou para o registro do ato, e o acervo é gerado de novo.

## Contribuir com código

```bash
git clone https://github.com/OlimpioV/CVM-normas.git
cd CVM-normas
python -m venv .venv
.venv/bin/pip install -r requirements.txt -e ".[testes]"   # no Windows: .venv\Scripts\pip
.venv/bin/python -m pytest
```

- Os testes rodam sem rede. Testes que acessam a CVM levam a marca `rede` e só rodam com `pytest -m rede`.
- Inclua testes para o que mudar, com uma página ou arquivo real da CVM em `tests/fixtures/` quando for o caso. Registre a origem em `tests/fixtures/LEIAME.md`.
- Mudanças de esquema do banco são feitas por migração (`armazenamento/banco.py`), nunca recriando os dados.
- Decisões de arquitetura novas entram em `docs/DECISOES.md`, com as alternativas consideradas.
- Mensagens de commit, código e documentação em português.

## Licença das contribuições

Ao contribuir, você concorda que o código fica sob a GNU AGPL v3, com o termo de preservação dos créditos (`LICENSE` e `NOTICE`), e que o conteúdo do acervo fica sob CC BY 4.0 (`LICENSE-ACERVO`).
