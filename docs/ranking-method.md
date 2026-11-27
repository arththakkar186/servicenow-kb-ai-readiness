# Ranking and Opportunity Analysis

## Article ranking

For each **current** article: the number of tickets linked to it in `m2m_kb_task`, all time and in the last 12 months, plus the
date of the last link. Links to superseded or retired versions are not credited to the current article, so the ranking
reflects what the library will actually contain.

Use: the top of the list is reviewed first (quality, accuracy, format), because those articles will be retrieved most.

## Demand groups and coverage gaps

Tickets are grouped three ways:

| Dimension | Ticket type | Field |
|---|---|---|
| category | Incidents | `category` |
| ci | Incidents | `cmdb_ci` |
| catalog_item | Requests | `cat_item` |

For each group the pipeline reports how many tickets ever had an article attached (**coverage**). High volume with low coverage
means people keep asking and nothing gets reused: a gap where a new or better article, or a self-service form, pays off most.

## Request mix

The share of all service requests by catalog item. One item dominating the mix (in the mock data, temporary local admin
rights at about 62%) is the strongest single self-service or automation candidate. Options for that kind of request, in
increasing order of effort:

1. a clear article and catalog guidance, which reduces bad requests,
2. a pre-approved, time-boxed elevation workflow (for example Intune Endpoint Privilege Management or Entra PIM-style just-in-time access),
3. removing the need, by packaging the software requests that drive elevation.

## Link recency

The share of all ticket-to-article links created in the last 12 months. If it is lower than the share of tickets opened in the
same window, agents are attaching articles less often than before, which is a process signal as well as a content one.
