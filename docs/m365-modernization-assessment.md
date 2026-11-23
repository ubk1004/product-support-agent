# Modernizing Microsoft 365: Assessment and Recommendations

## The question

> Your organization is planning to modernize its Microsoft 365 environment to improve collaboration, content management, search, security, and AI readiness. Describe how you would assess the current Microsoft 365 architecture and identify gaps related to identity, governance, SharePoint, Teams, OneDrive, Exchange Online, Microsoft Search, compliance, and AI-enabled services such as Microsoft 365 Copilot. What recommendations would you make to optimize the environment for scalability, security, user adoption, and future AI capabilities?

## My answer

### The idea behind my approach

A Microsoft 365 modernization is not one project. It is several connected ones: identity, governance, content and collaboration (SharePoint, Teams, OneDrive), email, search, compliance, and AI. They depend on each other in a clear order. Identity decides who gets in. Governance and compliance decide what people can reach and what happens to it. Content and search decide what can be found. AI sits on top and inherits all of it.

That last point is why AI changes the urgency more than the nature of the work. Copilot and agents respect existing permissions, but a lot of content is open on paper and safe only because nobody finds it. A file in a forgotten site shared with "everyone" is protected by obscurity. AI search across mail, chats, meetings and files removes that cover. The permissions stay the same, but the effective exposure grows. And it is no longer only about people: agents are becoming users of the tenant too.

So I would treat this as a tenant clean-up and governance program first, with AI as the payoff and not the starting point.

Three Microsoft platforms carry most of the security and compliance load, and it helps to keep their roles straight:

| Platform | Its job in this program |
|---|---|
| **Microsoft Entra** | Identity and access. Decides who, and what (people, apps, agents), can sign in and what they can reach. |
| **Microsoft Purview** | Data protection and compliance. Sensitivity labels, data loss prevention, retention, audit and eDiscovery, plus visibility into how AI uses data. It protects the data itself. |
| **Microsoft Defender** | Threat protection and response. Detects and blocks attacks across email, collaboration apps, devices, identities and cloud apps, and gives the security team one place to investigate. |

Put simply: Entra decides who gets in, Purview decides what happens to the data, and Defender watches for attacks and responds. They share signals, which is why Microsoft's AI risk dashboard (still in preview) combines all three.

### How I would assess the current state

1. **Talk to people first.** I'd meet IT, security, compliance, and a few business teams to learn what hurts, what is already planned, and where the risks are.
2. **Pull evidence from the tenant.** Opinions are not enough. I'd use the built-in reports and scores (secure score, SharePoint and Teams usage and sharing reports, mail flow and audit data) to see how things really are.
3. **Compare against a standard.** I'd map findings to a framework such as Zero Trust and Microsoft's own baselines, then rate each gap by risk and effort.
4. **Agree on a short list.** The output is a prioritized list of gaps with owners, not a long report nobody reads.

### Where I usually find gaps

| Area | What I look for |
|---|---|
| **Identity** | Weak or inconsistent MFA, legacy sign-in methods still allowed, too many permanent admins, no access reviews, stale guest accounts. Also non-human identities: old app registrations and service accounts with broad rights, secrets that never expire, and agents with no named owner. |
| **Governance** | No clear owner for sites and teams, sprawl, no lifecycle or naming rules, unmanaged guest sharing. |
| **SharePoint and OneDrive** | Oversharing ("everyone" links and broad groups), inactive sites, no data classification, no plan for departing users' files. |
| **Teams** | Unmanaged team creation, duplicate teams, unclear channel and meeting policies, guests with too much access. |
| **Exchange Online** | Apps still using old protocols (EWS, basic auth), weak anti-phishing settings, shared mailboxes with no owner. |
| **Microsoft Search** | Poor findability because of missing metadata, outdated content, and no curated answers or connectors for key systems. |
| **Compliance** | No sensitivity labels, retention applied inconsistently, data loss prevention not tested, audit not reviewed. |
| **Threat protection** | Defender protections left at defaults or not switched on, alerts nobody triages, no agreed incident process, no one watching for risky sign-ins or compromised accounts. |
| **Copilot and AI** | No readiness checks, no pilot plan, no policy on who can build agents or what they can access, no agent inventory (including agents built outside Microsoft 365), no way to measure value or cost. |

### What I would recommend

**1. Fix identity first (Entra).** Phishing-resistant MFA, starting with admins and then everyone else, Conditional Access that covers all users and apps, least-privilege admin roles, and regular access reviews. Nothing else is safe without this.

**2. Treat agents and service accounts as identities.** Agents sign in as non-human identities, and these are usually the least governed identities in the tenant. Each one needs its own identity, a named human owner, only the access its job needs, and no passwords or keys stored in code. The details are in "Governing agents" below.

**3. Clean up oversharing before a broad Copilot rollout.** Find and fix overshared sites, remove stale content and inactive sites, and set sensible defaults for sharing links. Until the clean-up is done, I'd also hide the riskiest sites from Copilot and agents. That is a temporary bridge, not a fix. The real fix is correcting the permissions.

**4. Add protection that works automatically (Purview and Defender).** With Purview: sensitivity labels, data loss prevention, retention, audit switched on, and lifecycle policies for sites and teams. Purview also shows how Copilot and agents touch sensitive data and can restrict what they process. With Defender: anti-phishing and safe attachment and link protection for email and collaboration apps, device protection, and alerts brought into one place with a named team and a clear process to triage them. Protection that nobody watches is only half a control. Manual review does not scale, so I'd automate wherever possible.

**5. Make Teams, SharePoint, and OneDrive work together.** A simple, clear model: Teams for conversation and meetings, SharePoint for team content, OneDrive for personal files. Provisioning should be easy but governed, with a named owner for each workspace.

**6. Improve search.** Better metadata, retire old content, and connect the main business systems so that search and Copilot find the right answer.

**7. Retire old email dependencies, and do it now.** This one has a deadline. Microsoft is disabling Exchange Web Services (EWS) in stages from October 2026 and plans to finish in April 2027. Password-based SMTP is due to be switched off by default for existing tenants at the end of December 2026. You can turn it back on, but that only buys time. I'd use the admin center usage reports to find which apps still depend on these, then move them to Microsoft Graph or modern authentication. Third-party products need checking too, not just in-house code.

**8. Design for scale.** What works for 50 sites and 20 teams breaks at 5,000. I'd rely on automation instead of admin effort: lifecycle policies with ownership and expiry, templates and hub sites so new workspaces start consistent, and permissions managed through groups and policy instead of per person. Reporting should be scripted and repeatable, and multi-geo or data residency needs should be settled early if the organization works across regions.

**9. Start Copilot with a pilot.** Pick a few teams with real use cases, include some skeptics, set success measures up front, and learn before scaling.

**10. Invest in adoption.** Training based on real jobs, champions in each department, clear guidance on what is safe to ask, and a place to share good prompts. Technology alone does not create value.

**11. Keep running it.** Permissions drift and new agents appear. I'd set up regular reviews, a governance group, and a small set of reports for leadership.

### Looking ahead: Microsoft IQ

Microsoft now groups its AI context services under the name **Microsoft IQ**, so that agents and Copilot share one understanding of the organization instead of each team wiring up its own data. **Work IQ** covers how people work (collaboration and workflows in Microsoft 365). **Fabric IQ** covers the state of the business (entities, relationships and rules over data in Fabric). **Foundry IQ** covers curated knowledge such as policies and authoritative documents. **Web IQ** brings in fresh public web information.

For a Microsoft 365 modernization, three points matter:

- **Your tenant's quality becomes the AI's quality.** Work IQ works over mail, files, chats and sites, and Foundry IQ can use SharePoint as a knowledge source. Stale, duplicated or overshared content flows into everything built on it. The clean-up in recommendations 3 to 6 is the preparation.
- **Permissions carry through, but only if they are right.** Microsoft's documentation says Work IQ actions run in the context of a specific user, and Foundry IQ syncs access lists and honors sensitivity labels. That is good design, but the clean-up still has to be done at the source.
- **Agent access reaches beyond Copilot, and it has a cost.** Custom and third-party agents can use Work IQ through standard interfaces, and Microsoft documents usage-based billing for it. So the agent inventory must cover agents built outside the Microsoft 365 admin center, and someone must own the budget.

I would not adopt the whole stack at once. Pick the use case first and start where the data is already clean and owned. Some parts, such as Fabric IQ ontology, are documented as preview, so I would check status and licensing at the time of each decision and keep preview features out of critical processes.

### Governing agents

Once agents multiply, the question changes from "who can open this file?" to "what is this agent allowed to do, and who answers for it?" Microsoft Agent 365 is Microsoft's management layer for this. It gives one view of the agents in the organization, from Microsoft, partners and your own teams, with owners, usage and risk, plus approval, policy and cost controls, and it brings in signals from Defender, Entra and Purview. It is licensed per user, so I would confirm what the agreement covers before designing around it.

Tooling helps, but the safeguards matter more than the product:

| Safeguard | In one line |
|---|---|
| **One inventory** | Every agent is registered, wherever it was built. What isn't listed can't be governed. |
| **A named owner** | A person is accountable for each agent, and orphaned agents are reassigned or retired. |
| **Approve before publish** | Controlled creation and sharing, with a short review for anything that touches sensitive data or takes actions. |
| **Least privilege** | Only the data and tools the job needs. Prefer acting as the user over acting on the agent's own rights, and never give agents admin roles. |
| **Human in the loop** | A person approves high-impact actions such as sending external mail, deleting data or paying money. |
| **Treat inputs as untrusted** | Emails, web pages and documents an agent reads can contain hostile instructions, so limit what an agent can do after reading them. |
| **Log, watch, and be able to stop it** | Activity is audited, risky agents are flagged, and there is a fast way to block one. |
| **Review and retire** | Agents are re-approved on a schedule, and unused ones are removed. |

If I had to pick three: **a named owner, least privilege, and a fast way to stop an agent**. Most of the rest follows from those.

### Roadmap in three steps

| When | Focus |
|---|---|
| **First 90 days** | Baseline assessment, identity fixes, inventory of app and agent identities, oversharing clean-up on the highest-risk sites, threat protection basics and alert triage, EWS and SMTP dependency fixes (these have dates). |
| **3 to 6 months** | Labels, data loss prevention, lifecycle rules, Teams and SharePoint governance, agent owners and approval rules in place, Copilot pilot. |
| **6 to 12 months** | Wider Copilot rollout, adoption program, agents and connectors under governance with regular reviews, first agent use cases where the data is ready, ongoing monitoring. |

### How I would know it worked

- Fewer overshared files and inactive sites.
- Higher share of users on strong MFA and fewer standing admin accounts.
- More content labeled and protected.
- A better secure score, and security alerts handled within an agreed time.
- Every agent and service identity has a named owner, and unused ones are gone.
- No EWS or password-based SMTP dependencies left by the Microsoft deadlines.
- Copilot adoption and satisfaction among pilot users, and time saved on real tasks.
- Fewer security incidents and support tickets related to access and sharing.

### Risks to watch

- **Rolling out AI too early** and exposing content people should never have had access to.
- **Over-restricting** and pushing people to unsanctioned tools. Governance should help people, not block them.
- **No ownership.** If sites, teams, agents and policies have no owner, the clean-up will not last.
- **Agent sprawl.** Agents are easy to create and easy to forget. An agent with broad access and no owner is a bigger risk than an overshared folder, because it can act, not just be read.
- **Relying on features that are still maturing.** Agent identity, the IQ services and AI-specific security dashboards are new and some parts are in preview. Check the current status and licensing before building a process around them.
