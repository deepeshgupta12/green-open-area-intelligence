"""Backend QA agents for master plan analyses.

* :mod:`reviewer` judges an analysis against the playbook and the image.
* :mod:`fixer` resolves the reviewer's findings with the extractor's own
  verified tools and hands the result back for another review.
* :mod:`teacher` maintains the playbook both agents read, distilling new
  acceptance rules, rejection cases and fix recipes from each cycle.
* :mod:`orchestrator` runs the bounded review -> fix -> review loop.
"""
