# Product Support Agent #
This repository contains a small AI-enabled application that demonstrates architecture judgment, secure production thinking, hands-on engineering depth, and the ability to move from prototype to an operable solution.

## Goal ##

The Goals is to use the following URLs which contains the Product list page and the search results API page as the sources and to design and build a working AI agent (select any model) to answer questions about supported products and their resources. 

1. URLs https://my.opentext.com/support/products/ and API https://my.opentext.com/api/web/support/search-results?start=1&maxResults=5&text=*. If none of these works then load from the feed https://my.opentext.com/api/web/feed/product. For each product there is a page hosted under https://my.opentext.com/support/products/{ProductCode} location where ProductCode is the "slug" property of the feed data. Each of the product support page contains knowledge articles and supporting documentations, retrieve the details from those documenation unless they are protected by authentication.

2. Future requirement is to expand the agentic capability to the full support and service management system (OpenText Service Management). 

3. Produce a concise architecture showing application components, identity and access, data flow, model interaction, trust boundaries, deployment, monitoring, and support ownership. 

4. Document architecture decisions, security and privacy considerations, assumptions, risks, trade-offs, production-readiness gaps, and a phased path from proof of concept to production.

## Architecture Considerations ##

1. I as a Senior AI Solution Architect is looking for a decoupled ingestion, Retrieval Tooling and Agentic Orchestration Architecture that would retrieve/ fetch the product listing and queries the search API with controlled pagination. It would honor the HTTP response types and act accordinlgy, as an example, if the status code is HTTP 401 then it would avoid loading the page since this demonstration should work with anonymous access alone. OpenText has multiple product knowlede/ documentations which are protected by Customer Authorization, I would skil thopse records entrirely after recording at a central place about the reason. The ingestion should run through a queue, where the entries would be loaded from the Product list, each queue item would store only one product detail, and the ingestion worker would take one item from the queue, fetch the relevant details from the supporting URLs, run the details through embedding and store it in the knowledge source. It should record the details about the operation, especially whether it is a success or failure. For this MVP I would like to select 100 products randomly from the Product list and have only those 100 ingested. I will keep the list of 100 selected product so that I can surface the names to the chat agent which will be used by the endusers during the demonstration. I would clearly indicate that this is a demo process and only the list of 100 products got ingested to avoid requiring additional infrastructure and also to avoid putting load on OpenText's infrastructure.
2. If the product list is empty then the ingestion and normalization process would terminate. If there is a rate limitation with HTTP 429 status code then I would check for suggested retry time and perform exponential backoff before retrying.
3. The ingestion process should normalize the results into a canonical document schema for idempotent operations and delta updates for subsequent runs.
4. I need a hybrid search implementaion since the endusers could search with keyword/ metadata and also through semantic meanings
5. I would keep the source URLs so that I can present the actual URL with the search results in the agent.
6. For the agent and orchestration layer I will use an LLM with structured tool/ function calling plus retrieval augmented generation (RAG)
7. I would enforce strict context grounding, prompt injection related defense and PII/SPI/secret redaction from logs.
8. I don't want to show the past search histories to the enduser in this MVP but I would retail all the logs/ traces/ queries/ responses from all user sessions so that those can be reviewed later to improve the experience and detect malicious attempts.
9. I would keep the embedding and a chat completion model behind a gateway so that I can change the models in the future without changing the code.
10. I need every claim about a supported product or resource to map back to a retrieved source URL/ID and do not want the model to invent links or resource ever.
11. I need to include OpenTelemetry based AI request tracing, logging and metrics, which would be sent to any capable product like Aspire or Arize Phoenix.
12. I need an offline evaluation dataset to test factual grounding, citation accuracy etc.
13. I would include AI Gateway, managed identity based authentication, automated build, deployment, code quality analysis, SAST, DAST and IAST validations.
14. I also need to prepare a phased path to take this proof of concept demonstration to Production where real users can use it. This will have usability, accessibility etc. validations to ensure that I am building a product what will be helpful to the endusers and not just a working prototype that works but not useful for anyone.
15. For each of the phases I want end to end testability. Each of the steps should be testable independently and completion of a phase require successful execution of the relevant test cases. I want unit test, integration test, end to end test etc.
16. I want to ensure that the project repository has proper structure so that it's easily readable and understandable by my other colleagues. All architectural decisions are logged, appropriate architecture documentations are created with architecture diagrams created in mermaid syntax.
17. Use a TypeScript React/Next.js frontend for the user-facing chat interface and a Python FastAPI backend. Build agents in Python with Microsoft Agent Framework. Use MongoDB locally and Azure Cosmos DB for MongoDB in the cloud. Use the user-provided Azure AI Search service for both local and cloud search; do not add a local vector store. Use LiteLLM locally and Azure API Management in the cloud as model gateways. Use system-assigned managed identity for cloud application access where supported, and Azure Key Vault for cloud secrets. Defer caching unless measurements justify it. Use Azurite locally and Azure Storage Queue in the cloud. Use Podman for local development.
18. I need to create a infrastructure deployment pipeline based on Bicep, which will have infrastructure as code scripts for the entire cloud infrastructure. This will include a Azure Virtual Network, Azure APIM will be deployed in external mode with VENT integration. All the backed services, agents, data store, queue etc. will be under the VENT with appropriate subnets. I will need Log Analytics workspace and Azure Monitor for the logs/ metrics and traces.
19. I will need a code build pipeline for the UI, backend API, AI Agents
20. I will need a code deployment pipeline for the UI, backend API and AI Agents
21. To host the backend use Azure Container Apps.
22. Use GitHub Actions for the build and deployment pipelines