I'd like to set up a local lab on my home machine, to mimic the prod environment.
All of our code should be written in Python, using uv.
Each of these projects we create can just be in a subfolder (One project per folder).

So, that would include:
- oauth-idp (a custom one; to mimic Okta)
  - This way I can control like an administrator would, and create users, permit clients, etc.
- chat-front; a new service i'm creating (is the second thing I want to explore)
  - This will be a very basic Pydantic AI implementation 
    - a simple agent that can check the weather and using tool calls (An example of inference and tool calling via mcp) (Ask me to provide a link to the weather demo for Pydantic)
- chat-back; a new service I'm creating (This is the first thing I want to explore)
  - This will be a kind of AI inference proxy. It will accept HTTP requests in the shape of OpenAI API Compatible (inference requests), and it will return the inference response. (Ask me to provide the OpenAI documentation)
  - But in the background it will be translating the request To one of two target AI providers.
    - The correct provider will be determined by a prefix on the model name (ie. `copilot:claude-sonnet-4.6` means use Copilot AI Provider. `xai:grok-fast-1` means use xAI AI Provider) (Ask me to provide the folder where the source code is you can copy from because I've implemented this a few times by now)
  - each reuqest is sending Logs, metrics, traces, spans via otel to mcp-gw (Ask me for the documentation showing the structure of the otel data for ai)
- mcp-gw; a new service I'm creating (This is the third thing I want to explore)
  - This is an MCP server that will provide mock tool call implementations for LLMs to use 
- Grafana tempo 
  - This will allow me to visualize otel traces, logs, metrics


Since oauth-idp is a dependency of (chat-front, chat-back, and mcp-gw), Let's start with that first.

we can create it in this working directory.
and then we can run some smoke tests against it to prove it works.
- The scenario is that.. We're creating a new app (ie. chat-front) And we want the app to be recognized by the IDP 
- We want the app (ie. chat-front) to be able to validate its own users' requests to ensure they are authetnticated against the IDP 


My end goal is the following workflow:
- Admin adds new chat-front app  to oauth-idp
- User authenticates to chat-front using oauth flow
- chat-front sends an llm inference request to chat-back, and receives a valid response
  - chat-back llm sends a tool_call request to mcp-gw, and receives a valid (mock) response
- traces for the above requests are visible in grafana tempo  (sent via otel from chat-back)


references:
- otel gen ai spec https://opentelemetry.io/docs/specs/semconv/gen-ai/
- pydantic ai weather agent demo https://ai.pydantic.dev/examples/weather-agent/#example-code
- subd example code for multi-ai provider support /workspace/subd/
- openai api docs https://developers.openai.com/api/reference/resources/responses/methods/create