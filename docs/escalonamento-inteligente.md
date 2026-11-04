# Escalonamento inteligente de incidentes

Proposta de produto para o Watchyard no Mac. O mesmo desenho permite executar
o serviço num VPS com ligação privada às câmaras. Os valores abaixo são
parâmetros iniciais do piloto, sujeitos a validação com imagens das câmaras reais.

**História principal.** Quando estou fora de casa, quero que o Watchyard me
avise por telefone se observar um incidente sério que merece atenção imediata.
Quero receber os restantes alertas no Telegram, com contexto suficiente para
decidir o que fazer e sem pagar por análise contínua.

## Piloto local disponível na versão 0.8.10

1. Em **Cameras**, abrir as definições da câmara. Em **Area to edit**, desenhar
   **Expected access** e **Restricted access**. As áreas de revisão podem
   sobrepor-se. Nesse caso prevalece a área restrita. Para que uma trajetória
   seja registada, a pessoa ainda tem de entrar na área de alerta configurada.
2. Em **Settings → Incident simulation**, selecionar **Away** e um período de
   1, 4, 8 ou 24 horas. O modo inicial é **Paused**. Também se pode usar
   `/presence`, `/presence home`, `/presence away 4` e `/presence paused`
   numa conta de gestor no Telegram. Ao terminar a ausência, a presença passa
   a **desconhecida**. Esta versão usa presença manual.
3. Em **Recent decisions**, verificar a decisão e abrir o replay. O piloto
   marca revisão urgente quando observa uma entrada na área restrita e pelo
   menos 8 segundos de permanência, com observações repetidas e intervalos de
   até 3 segundos, enquanto a casa está ausente ou com presença desconhecida.
   Se a primeira observação já estiver dentro da zona, fica como evidência
   insuficiente. Pausas, horários e categorias guardadas apenas no histórico são respeitados na simulação.
4. Rever os falsos alarmes no histórico. A decisão e a revisão ficam
   disponíveis lado a lado. Cada decisão usa a trajetória local da câmara,
   com evidência limitada a posição e tempo. O mesmo acontecimento pode
   aparecer em duas câmaras. A correlação existente continua disponível na
   atividade. As decisões ficam em SQLite até expirar o evento associado.

Este piloto usa a cadência atual de deteção e regista decisões quando o motivo
muda. Preserva a evidência da primeira decisão urgente do evento. Os marcos
seguintes abrangem fila para análise externa, correlação de incidentes para
voz, fotogramas selecionados, Home Assistant, MCP e chamadas.

## 1. Fluxo e pontos de integração

1. **Detetar e agrupar no Mac.** Reutilizar o detetor Core ML, o seguimento de
   objetos, as zonas e os eventos do SQLite. Manter a análise habitual a 1 fps
   como base do piloto. A atividade segue o fluxo existente de histórico e
   Telegram. A triagem corre numa fila à parte, com concorrência de um trabalho.
2. **Aplicar regras locais.** Cruzar a sequência observada com a zona, a
   qualidade das imagens, a presença da casa e os sensores opcionais. A maioria
   dos eventos termina aqui. Se o evento for banal e o utilizador desejar menos
   ruído, permitir resumos silenciosos de entregas prováveis, mediante opção.
3. **Consultar um modelo visual por exceção.** Quando a decisão depende de
   interpretar imagens, selecionar até três fotogramas com hora e ordem
   (aproximação, ação, desfecho). O Mac limita custo, tempo e dados enviados.
   Um adaptador pode usar Grok ou outro modelo visual validado. A triagem local
   também funciona com orçamento externo de €0.
4. **Escalonar por política.** O Watchyard combina evidências locais e o
   parecer do modelo. Envia uma atualização urgente com replay quando cabível.
   A chamada é uma ação separada, reservada para a política de voz. O mesmo
   incidente pode ganhar evidência sem disparar outra chamada. Pausa e desarme
   têm precedência, incluindo quando a decisão já está na fila.

O Watchyard já guarda primeiro e último avistamento, um snapshot e replays
dependentes das capacidades do gravador. Para a triagem, recolher fotogramas
dos candidatos num pequeno buffer por câmara e persistir apenas os selecionados.
Nos gravadores compatíveis, usar replay como contexto adicional quando chegar
a tempo. RTSP simples usa o buffer. Se faltar contexto, devolver
`inconclusivo`. O agrupamento atual pode acontecer na entrega ao Telegram e
aceitar correspondências só pelo tempo. Criar um identificador persistente de
incidente antes da entrega, mesmo numa instalação sem Telegram. Proximidade
temporal serve para apresentar eventos juntos. Para deduplicar chamadas, exigir
continuidade de trajetória, correspondência corroborada entre vistas ou um
mesmo disparo de sensor. Manter trajetórias simultâneas distintas. Evitar
dependência de pares de câmaras configurados. [Agrupamento atual](activity-correlation.md)
· [Replays](replay-and-clips.md) · [Webhook atual](cameras-and-notifications.md#notification-providers)

## 2. Presença da casa

| Fonte | Uso proposto |
| --- | --- |
| Modo manual no painel ou Telegram | Começar com **Armar como ausente** com validade definida, **Em casa** e **Pausa**. Permitir marcar convidados temporários. O modo manual expressa a intenção de armar e fica visível com o motivo e o prazo. Sinal recente de ocupação continua a travar a chamada automática. |
| Wi-Fi do router | Presença recente de um dispositivo registado é sinal de que pode haver alguém em casa. Desconexão, Wi-Fi desligado, MAC alterado e falha do router passam a desconhecido. Usar a integração do router com Home Assistant, se suportada. |
| Geofence no iPhone e Android | Usar Home Assistant Companion com partilha limitada à zona quando disponível. Um adaptador envia ao Watchyard só `em_casa`, `fora` ou `desconhecido`, fonte, hora real e saúde da integração. Validar no piloto entregas em segundo plano e fora do Wi-Fi por canal privado autenticado. |
| Contacto de porta ou campainha | Opcional para corroborar abertura, toque e ordem dos acontecimentos. Útil em caso de oclusão, pouca luz ou câmara indisponível. |

A casa fica **em casa** se houver presença fiável de um morador ou convidado.
Fica **fora** quando todos os moradores registados têm saída confirmada,
os sinais de presença estão operacionais, e passou um período de estabilização
(inicialmente dois minutos), ou por armação manual válida sem sinais
contraditórios. Tudo o resto fica **desconhecido**, incluindo arranque sem
estado reconciliado, permissões revogadas, fonte desatualizada, conflito de
sinais e cobertura incompleta de moradores sem modo manual. Para a geofence,
guardar a última transição real e verificar a saúde do canal separadamente.
Uma leitura repetida do mesmo estado tem a hora original. Expirar sinais
conforme a fonte e voltar a desconhecido se a entrega em segundo plano deixar
de ser verificável. Um telemóvel em casa é só um indicador. No estado
desconhecido, um incidente grave pode gerar Telegram urgente para revisão,
com chamadas automáticas desativadas. Revalidar a presença na hora de ligar.

A automatização deve ser opcional por morador e revogável. O painel mostra
estado agregado, fonte, idade do sinal e o motivo de estar armado ou não.
Conservar apenas estado recente e decisões necessárias para auditoria. Uma app
nativa própria só entra se houver necessidade que o Companion não cubra.
[Home Assistant Companion e geofence](https://companion.home-assistant.io/docs/core/location/)
· [Rastreadores do Home Assistant](https://www.home-assistant.io/integrations/device_tracker/)
· [Core Location no iOS](https://developer.apple.com/documentation/CoreLocation/monitoring-the-user-s-proximity-to-geographic-regions)

## 3. Matriz de decisão

Configurar por instalação polígonos de **acesso esperado** (por exemplo, o
portão usado para entregas) e **acesso restrito** (por exemplo, a entrada
lateral). As regras usam a função da zona e a sequência observada, com uma ou
várias câmaras. As zonas de alerta e a máscara de privacidade são controlos
distintos.

| Evidência | Ação inicial | Análise externa |
| --- | --- | --- |
| Animal, sombra, reflexo ou pista de pessoa sem consistência entre fotogramas | Marcar como provável falso positivo apenas com evidência suficiente. Caso contrário, assinalar como inconclusivo. Guardar para revisão. | Zero por defeito. |
| Pessoa aproxima-se pela entrada habitual, deixa um volume e sai pelo mesmo acesso | Etiqueta **possível entrega** e alerta normal ou silencioso. Uma encomenda esperada reforça o contexto. | Zero por defeito. |
| Pessoa toca à campainha ou espera na zona de visita | Etiqueta **possível visita**, com alerta normal. Um horário de visita ajuda. A identidade de um vizinho fica para confirmação do morador. | Zero por defeito. |
| Casa em modo ausente, pessoa confirmada em vários fotogramas e permanência anormal em zona restrita ou ação ambígua junto ao acesso | Enviar o alerta normal imediatamente. Se um parecer puder mudar a ação, pedir uma avaliação e atualizar o incidente. | Uma avaliação por incidente no piloto. |
| Entrada numa zona restrita com evidência corroborada, como transposição seguida de permanência e contacto de porta fora de uma janela autorizada | Telegram urgente com evidência. Chamada ao proprietário se a política de voz estiver armada, a presença continuar válida e o incidente estiver recente e pendente. | Opcional. Evidência local suficiente pode escalar sem custo de modelo. |
| Imagem escura, fonte de presença indisponível, modelo contraditório, orçamento esgotado ou serviço externo indisponível | Preservar o alerta base. Se os sinais locais forem fortes, marcar **revisão urgente**. Exibir a razão da decisão. | Devolver **inconclusivo** quando a evidência não chega. |

O modelo devolve JSON validado com categoria, observações com referência aos
fotogramas, sinais contrários, qualidade da evidência e resumo curto em português.
Exigir um enum pequeno (`provavel_entrega`, `provavel_visita`,
`provavel_falso_positivo`, `atividade_atipica`, `inconclusivo`). Um parecer
pode promover um incidente para revisão, e uma hipótese de entrega ou visita
não cancela sinais locais fortes. Uniforme, rosto, texto na imagem e confiança
declarada pelo modelo têm peso insuficiente para identificar uma pessoa,
autorizar acesso ou ligar a alguém. Para frases de voz, usar um modelo de
mensagem preenchido apenas com factos validados. [Visão na API de Grok](https://docs.x.ai/developers/model-capabilities/images/understanding)
· [Saída estruturada](https://docs.x.ai/developers/model-capabilities/text/structured-outputs)

## 4. Integração de agentes

- **Webhook para avisar.** Usar a assinatura HMAC, timestamp, chave de
  idempotência e versão do webhook existente. Acrescentar um contrato para
  incidentes com `incident_id`, revisão, hora, gravidade e prazo. O consumidor
  valida assinatura e janela temporal e deduplica reentregas. Entregas por evento
  do webhook atual e entregas por incidente são contratos separados. O payload
  de incidente leva metadados mínimos, com destinos configurados pelo gestor.
- **API privada para consultar.** Credencial própria por integração com escopos
  `incidents:read` e `evidence:read`, este último opcional e limitado por
  câmara, incidente e prazo. Separar a autenticação de agentes das sessões de
  browser, inclusive do acesso implícito do Mac. Revogar, rodar e auditar
  credenciais, limitar tamanho e frequência das respostas e aplicar os escopos
  também no acesso a cada fotograma. O agente recebe o pacote aprovado pelo
  Watchyard, sem tokens do gravador ou do Telegram, matrículas, GPS ou acesso
  direto a streams. Tratar texto em imagens, mensagens e pareceres como dados.
  Validar a resposta, incluindo referências a fotogramas do próprio incidente,
  e processá-la com um esquema que não concede permissões.
- **MCP para dar ferramentas ao agente.** Adaptador fino sobre a mesma API.
  Ferramentas iniciais `list_recent_incidents`, `get_incident` e
  `get_incident_evidence`. Começar em `stdio` para um agente que corre
  no Mac. Para um cliente remoto compatível, usar Streamable HTTP em rede
  privada, TLS, validação de Origin e autorização conforme a especificação
  MCP. O fluxo automático funciona apenas com fila, webhook e API. O agente
  consulta e interpreta. As ações de telefonia ficam no executor de política
  do Watchyard. Validar o cliente e o transporte antes de prometer suporte a
  um bot específico. [Transportes MCP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
  · [Autorização MCP](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

## 5. Chamadas, orçamento e tratamento de falhas

- **€0 adicional.** Usar modo manual ou Home Assistant já instalado, regras
  locais e Telegram. Uma mensagem de voz opcional é um áudio reproduzível no
  chat. A API de bots do Telegram oferece esse envio. Para tocar como chamada
  para um número telefónico, usar um provedor de voz ou uma linha SIP
  configurada. [Telegram Bot API](https://core.telegram.org/bots/api#sendvoice)
- **Telefonia opcional.** Avaliar Twilio Programmable Voice e, se houver linha
  disponível, SIP. Confirmar custos de destino, número de origem, eventuais
  mensalidades e voz portuguesa antes de ativar. Começar com mensagem curta
  sintetizada e confirmação por tecla ou no Telegram. Exemplo
  “Watchyard. Às 21h14, a câmara da entrada registou uma pessoa na zona
  restrita e o sensor indicou abertura do portão. Consulte o alerta.
  Prima 1 para confirmar a receção.” Confirmação significa recebido,
  independentemente de o incidente ter sido verificado. Um estado de chamada
  concluída ou um voicemail não conta como confirmação. Para o piloto, pode-se
  usar a consulta do estado ao provedor e confirmar pelo Telegram. Se for
  necessário receber callbacks de voz ou DTMF, usar um endpoint HTTPS isolado
  com assinatura verificada, sem publicar o painel, NVR ou MCP.
  [Chamadas de saída](https://www.twilio.com/docs/voice/tutorials/how-to-make-outbound-phone-calls)
  · [Webhooks de voz](https://www.twilio.com/docs/usage/webhooks/voice-webhooks)
  · [Segurança Twilio](https://www.twilio.com/docs/usage/security)
  · [Tarifário para Portugal](https://www.twilio.com/en-us/voice/pricing/pt)
- **Escada de contacto.** Proprietário verificado primeiro. Um vizinho ou
  familiar pré-cadastrado e com consentimento pode ser contactado numa fase
  posterior, após autorização humana explícita do gestor para o incidente. O destino
  vem da lista aprovada, com números normalizados e verificados. Polícia e
  112 ficam sob decisão e ação humana. Números de emergência ficam bloqueados
  no executor. [Serviço 112 em Portugal](https://www.sg.mai.gov.pt/pt/Tecnologias/112pt/visaodoservico112/Pages/default.aspx)
- **Limites iniciais.** Defeito €0, com opt-ins separados para imagens em API
  externa e voz. Propor teto de duas avaliações externas por dia, uma por
  incidente, e no máximo três imagens e 20 s por avaliação. Uma chamada por
  incidente e destinatário, no máximo duas chamadas no total por dia durante
  o piloto. Expirar escalonamento aos três minutos do início do incidente e
  cancelar envio pendente se houver confirmação, desarme, pausa ou mudança de
  presença. Reservar custo antes de cada pedido, limitar tokens e duração da
  chamada e contabilizar pedidos de resultado ambíguo. Usar teto mensal do
  projeto e limite do fornecedor onde existir. Esgotar orçamento degrada para
  triagem e notificações locais.
- **Estado durável.** Usar uma outbox SQLite com transações, identidade estável
  de incidente, chave única por efeito e destinatário e ID do fornecedor.
  Revalidar política na execução. Depois de timeout ambíguo da telefonia,
  reconciliar com o fornecedor antes de considerar nova tentativa.
  Se não houver confirmação segura do estado, deixar a chamada como
  indeterminada e avisar pelo Telegram. Descartar chamadas expiradas no
  reinício. Mostrar no painel motivo, estado, hora, confirmações e custos
  estimados. O relógio da fila e as expirações independem do modelo.
- **Privacidade.** Verificar ângulo e captação na origem e limitar à propriedade
  conforme as orientações aplicáveis da CNPD. Máscaras e redução da imagem
  complementam essa configuração antes de qualquer envio. Enviar apenas
  fotogramas indispensáveis a provedor aprovado após validar tratamento,
  retenção e transferências. Propor até 30 dias para o registo local de decisões
  sem imagens, sujeito à política de retenção da instalação, e apagar o pacote
  temporário após a avaliação ou expiração. Áudio
  sintetizado sem gravação, endereço completo ou estado de ocupação.
  [Orientações da CNPD para videovigilância residencial](https://www.cnpd.pt/cidadaos/areas-tematicas/videovigilancia-por-vizinhos/)

## 6. Marcos e critérios de aceitação

| Marco | Entrega e condição para avançar |
| --- | --- |
| **M1. Presença manual e simulação local** | Motor de políticas, evidência, zonas, fila e histórico de decisões com modo **Simular**. Anotar exemplos de pessoa, entrega, visita, animais (incluindo aves), sombras e baixa luz. Simular incursões controladas com moradores autorizados, incluindo a mesma atividade em duas câmaras e duas pessoas distintas. Medir ruído, alertas urgentes em falta e latência. |
| **M2. Presença automática e resumo** | Adaptador Home Assistant e modo manual de recuperação. Testar no iPhone e Android bloqueados, saída e regresso, perda de rede, telemóvel deixado em casa e convidados. Uma fonte perdida, velha ou contraditória nunca implica casa vazia. Testar o modelo em modo sombra, com fotogramas autorizados, e comparar com regras locais sobre os mesmos casos. Aceitar o modelo apenas se melhorar a triagem sem aumentar incidentes graves perdidos no conjunto anotado. |
| **M3. Integrações e voz em piloto** | Validar autenticação, revogação, evidência limitada, webhook e deduplicação antes de oferecer MCP. Ligar primeiro em teste a um único número verificado. Exercitar confirmações, ocupado, voicemail, falhas de rede e de fornecedor, callbacks repetidos, reinício e orçamento esgotado. Habilitar voz real só após aprovação do gestor e revisão dos resultados do piloto. |

### Metas iniciais de aceitação

Separar a amostra usada para afinar as regras da amostra de validação.
Como ponto de partida, preparar 20 ensaios graves encenados e 60 casos
benignos ou ambíguos, distribuídos entre câmaras, dia e noite.

- Zero chamadas em casos de falso positivo, entregas, visitas, casa ocupada,
  presença incerta e eventos expirados. Reentregas não acrescentam chamadas.
  Um incidente com a mesma trajetória em duas câmaras produz no máximo uma chamada ao proprietário.
  Incidentes independentes continuam visíveis mesmo quando a quota de voz se esgota.
- Nos testes de corte de rede ou falta de contexto, o caminho normal do alerta
  continua sem aguardar o modelo. Medir p95 do tempo entre deteção confirmada e
  aviso inicial e comparar com a versão atual. Para incidentes elegíveis, meta
  preliminar de p95 até 30 segundos da elegibilidade ao início da chamada
  solicitada, medida separadamente do tempo até o telefone tocar.
- Almejar pelo menos 90% dos cenários graves encenados sinalizados para
  revisão urgente. Separar dia/noite e mostrar contagens absolutas, falsos
  escalonamentos e motivos para abstenção. O teste mede o conjunto encenado.
  Reportar também percentagem enviada ao modelo, custo e chamadas por semana,
  carga do Mac e se a análise por câmara mantém a cadência de base.
