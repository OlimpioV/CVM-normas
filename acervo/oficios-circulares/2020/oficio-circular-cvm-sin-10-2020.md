---
id: "oficio-circular-cvm-sin-10-2020"
titulo: "Ofício Circular CVM/SIN 10/20"
especie: "Ofício-Circular"
numero: "10"
ano: 2020
ementa: "Nova plataforma para envio do Informe Diário dos fundos de investimento."
data_edicao: "2020-08-10"
data_publicacao_dou: null
inicio_vigencia: null
fim_vigencia: null
situacao: "vigente"
situacao_fonte: "https://conteudo.cvm.gov.br/legislacao/oficios-circulares/sin/oc-sin-1020.html"
situacao_verificada_em: "2026-11-06"
ficha_oficial: "https://conteudo.cvm.gov.br/legislacao/oficios-circulares/sin/oc-sin-1020.html"
versao: "Original"
versao_aviso: "Redação original (não é texto consolidado)."
fonte: "https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/oficios-circulares/sin/anexos/oc-sin-1020/documentacao_tecnica_plataforma_supervisao.pdf"
fonte_sha256: "99df8397c7746761f092564acbf62117a4a6abdcde991c87bd8e4a26f9abe6eb"
fonte_coletada_em: "2026-11-06"
conversor: "pdf-pymupdf/5"
qualidade: "média: PDF oficial; camada de texto do PDF, sem segunda fonte oficial para conferência; divisão em parágrafos reconstruída; avisos: divisão em parágrafos reconstruída a partir do PDF"
relacoes: []
audiencias_publicas: []
justificativa_air: null
aviso_vigencia: "Situação conforme as marcações da ficha oficial da CVM consultada em 06/11/2026. Revogações feitas pelo texto de outras normas ainda não são cruzadas automaticamente; confirme a vigência na fonte oficial antes de citar."
aviso: "Texto convertido automaticamente a partir do arquivo oficial da CVM, apenas para consulta. Em caso de divergência, prevalece o original publicado pela CVM."
---

Autenticação CVMWeb

Mediante parâmetros de autenticação, retorna token de acesso para envio de informes ou acesso negado. Implementa o ‘Password Grant’ do OAuth, seguindo o padrão.

• URL https://web.cvm.gov.br/services/auth/login/cvmweb Não há ambiente de testes para esse método, mas o token retornado poderá ser usado para testar o processamento, conforme documentação a seguir.

• Method:

POST

• Headers necessários no Request

Nome Valor Content-Type application/json

• Corpo da requisição (Request body)

Objeto JSON com os parâmetros ‘cpf’ e ‘senha’, sendo as credenciais de acesso ao CVMWeb do usuário que irá enviar os informes. { “cpf”:11111111111, “senha”:”xxxxx” }

• Resposta esperada (sucesso):

Situação Código de retorno

HTTP

Corpo da resposta

Login válido 200 (OK) { "access_token": "xxxx", "token_type": "bearer", "expires_in": 3600 }

Após o login bem sucedido, o retorno volta com três dados importantes:

• O token de acesso (access_token) • O tipo do token (por padrão, bearer) • O tempo de vida do token, em segundos o No exemplo acima, uma hora (padrão).

Com esses dados, sua aplicação já poderá enviar informes para o web service durante o tempo de vida do token. Após sua expiração, um novo token deverá ser gerado.

• Respostas com erro:

Situação Código de retorno

HTTP

Corpo da resposta

CPF/senha inválido(s) 401 (Unauthorized) { "error": "invalid_client", "error_description": "Credenciais invalidas" } Erro interno 500 (Internal Server Error)

{“error_description”:“descrição do erro”}

Processar Informes diários

Processa um XML com até 100 informes diários e retorna o resultado.

• URL

PRODUÇÃO: https://web.cvm.gov.br/services/informes/api/informe/diario

AMBIENTE DE TESTES/”SANDBOX”: https://web.cvm.gov.br/services/sandbox/informes/api/informe/diario

• Method:

POST

• Headers necessários no Request

Nome Valor Content-Type application/xml; charset=UTF-8 ou text/xml; charset=UTF-8 Authorization [Token_Type] [Access_Token]

O header Content-Type pode receber qualquer um dos valores especificados. Atente-se para o ‘encoding’ UTF-8, que é o esperado no corpo da requisição. O header Authorization receberá dois valores, separados por um espaço em branco, como colocado acima. O primeiro deles é o tipo do token (‘token type’), que é retornado pelo método de autenticação (padrão: bearer) e o segundo o próprio token de acesso (‘access_token’), também retornado pelo serviço.

Para o exemplo anterior, o header ficaria: Authorization: bearer xxxx

• Corpo da requisição (Request body)

No corpo da requisição deve ser enviado o XML de informe diário que já é enviado à CVM atualmente e cujo padrão pode ser encontrado em http://sistemas.cvm.gov.br -> Sistema CVMWeb -> Envio de Documentos -> Padrões de Arquivos - XML e Outros -> Informe Diário.

Apesar de não ser obrigatório, é recomendável enviar o XML sem formatação, quebras de linha ou espaços antes ou após as tags. O retorno do processamento devolve um hash de verificação (“checksum”) que nãoleva em consideração nenhum desses caracteres.

• Resposta esperada (sucesso):

Situação Código de retorno

HTTP

Corpo da resposta (exemplo; maiores detalhes abaixo)

Informe processado

200 (OK) { "protocoloRecebimento": 1234567, "statusGeralProcessamento": "P", "checksum": "ca46003634a7d2478c606759fd04ec32c7da9fe5887a8c54a348a 439f40aa60f", "dataHoraProcessamento": "14/07/2020 16:30:49", "totalInformesProcessados": 3, "detalhes": { "11.111.111/1111-11": { "protocoloProcessamento": 10000000, "statusProcessamento": "E", "mensagensAssociadas": [ "O usuário (CPF: XXXX) não possui permissão para enviar informe diário para este fundo", “mensagem de erro 2”, “mensagem de erro 3” ] }, "22.222.222/2222-22": { "protocoloProcessamento": 10000001, "statusProcessamento": "S", "mensagensAssociadas": [] } "11.111.111/1111-11": { "protocoloProcessamento": 10000000, "statusProcessamento": "E", "mensagensAssociadas": [ "Patrimônmio Líquido inválido"

] }

} }

A resposta esperada não quer dizer que o informe foi processado com sucesso, isso é detalhado no corpo do JSON retornado, como detalhado a seguir. Um código de retorno 200 implica que o processamento ocorreu sem falhas.

Detalhes do JSON de retorno

Chave Definição protocoloRecebimento Número do protocolo de recebimento –indica que a CVM recepcionou o informe com sucesso. Não implica automaticamente no processamento do mesmo. statusGeralProcessamento Indica o status geral do processamento do informe enviado, podendo ter os seguintes valores:

Valor Significado S Sucesso – Todos os informes recepcionados foram processados com sucesso. P Sucesso parcial.

Indica que nem todos os informes foram processados com sucesso. E Erro geral. Todos os informes enviados tiveram erros de validação. N Erro interno – Ocorreu algum erro nos servidores da

CVM durante o processamento.

Nesse caso, a orientação inicial é reenviar o informe e caso o erro persista, acionar o Suporte a

Sistemas da CVM.

checksum Esse campo é uma “hash” usando o algoritmo SHA-256 do XML enviado no corpo da requisição. Na geração do hash todos os espaços entre tags, no início e final do arquivo são removidos, bem como a quebras de linha. Por exemplo, o XML abaixo (formatado e com espaços entre tags): <CAB> <INF1>xxx</INF1> <INF2>qqq</INF2> </CAB> <CORPO> <A>b</A> <B>c</B> </CORPO> Irá ser convertido para a seguinte “String”, em linha única: <CAB><INF1>xxx</INF1><INF2>qqq</INF2> </CAB><CORPO><A>b</A><B>c</B></COR PO> É dessa última string que o checksum SHA-256 será gerado e retornado. dataHoraProcessamento Data e hora exata em que o processamento do informe foi efetuado. totalInformesProcessados Total de informes processados. detalhes Mapa com os detalhes do processamento. Cada chave no mapa é um CNPJ dos que foram enviados no informe e o valor é um objeto com três chaves, conforme detalhado abaixo. protocoloProcessamento

Número do protocolo de processamento para o CNPJ em questão. statusProcessamento Status do processamento do informe específico, podendo ter os valores:

Valor Significado S Sucesso E Erro mensagensAssociadas Lista de strings com mensagens detalhando os erros. Se o processamento tiver sido com sucesso, este campo será uma lista vazia.

• Respostas com erro:

Situação Código de retorno

HTTP

Corpo da resposta

Token de acesso inválido ou expirado

401 (Unauthorized)

Erro interno 500 (Internal Server Error)
