Semantic Scholar API Application Answers
========================================

1. How do you plan to use Semantic Scholar API in your project?
-------------------------------------------------------------

I am conducting a small-scale literature survey on recent computer-science papers. I use the Semantic Scholar API to look up missing abstracts and bibliographic details when I only have a title or DOI. My workflow is manual: I prepare a list of papers, then query S2 one by one to fill in the gaps. The project is for personal research only. I keep request rates low with a ~1-second delay between calls.

2. Which endpoints do you plan to use?
--------------------------------------

- GET /paper/search/match (look up a paper by title)
- POST /paper/batch (batch lookup by DOI or S2 ID)

3. How many requests per day do you anticipate using?
-----------------------------------------------------

At most a few hundred requests on days when I am actively working on the survey. Most days there are no requests at all. I stay well within the 1 req/sec limit.
