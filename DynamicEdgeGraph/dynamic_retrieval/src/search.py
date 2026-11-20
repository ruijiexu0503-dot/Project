"""Deterministic, budget-accounted two-hop graph traversal primitives."""
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Budget:
    max_unique_nodes: int=20; max_target_scores: int=120; max_route_updates: int=400
    unique_nodes: int=0; target_scores: int=0; route_updates: int=0
    def can(self, nodes=0, scores=0, routes=0): return self.unique_nodes+nodes<=self.max_unique_nodes and self.target_scores+scores<=self.max_target_scores and self.route_updates+routes<=self.max_route_updates
    def charge(self, nodes=0, scores=0, routes=0):
        if not self.can(nodes,scores,routes): raise RuntimeError("budget exceeded before action")
        self.unique_nodes+=nodes; self.target_scores+=scores; self.route_updates+=routes

def traverse(seeds, adjacency, score, budget=Budget(), max_hops=2, neighbors_per_expand=3, reserve_scores=0, reserve_routes=0):
    """Round-robin BFS; score(node,routes,path) is caller-owned and Gold-free."""
    seen, frontier, trace = set(), [], []
    for seed in seeds:
        if seed not in seen and budget.can(nodes=1): seen.add(seed); budget.charge(nodes=1); frontier.append((seed,0,[seed])); trace.append({"action":"seed","node":seed,"hop":0})
    cursor=0
    while cursor < len(frontier):
        source, hop, path = frontier[cursor]; cursor += 1
        if hop >= max_hops: trace.append({"action":"not_expanded_max_hops","node":source,"hop":hop}); continue
        candidates=[]
        for target, provenance in adjacency.get(source,[]):
            if target not in seen: candidates.append((target,provenance))
        candidates=sorted(candidates,key=lambda x:(str(x[1]),str(x[0])))[:neighbors_per_expand]
        for target, provenance in candidates:
            # One target score and one route update are charged before model access.
            if not budget.can(nodes=1,scores=1+reserve_scores,routes=1+reserve_routes): trace.append({"action":"budget_blocked","source":source,"target":target,"hop":hop+1}); continue
            seen.add(target); budget.charge(nodes=1,scores=1,routes=1)
            value=score(target,[(source,provenance)],path+[target]); frontier.append((target,hop+1,path+[target]))
            trace.append({"action":"visit","node":target,"parent":source,"hop":hop+1,"path":path+[target],"score":float(value),"provenance":provenance})
    return trace,budget
