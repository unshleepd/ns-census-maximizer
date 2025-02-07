import nationstates as ns
import trotterdam
import copy
import numpy as np

api = None
world = None

skip_issues = [0, 0, 0, 0]  # replace with the issue IDs you want to skip

with open("census_distribution.txt", "r") as file:
    census_distribution = eval("".join(file.readlines())) # yes, I'm aware that this is evil :P
    weights_by_world_mean = {key: 1/abs(val[0]) for key, val in census_distribution.items()}
    weights_by_world_spread = {key: 1/abs(val[1]) for key, val in census_distribution.items()}

def init(contact):
    """ Sets up connection to the nationstates api """
    global api, world
    api = ns.Nationstates("Instance of https://github.com/bekaertruben/ns-census-maximizer [contact: {}]".format(contact))
    world = api.world()

class CensusMaximizer:
    """ Solves issues by calculation maximum world census score increases """
    user : str
    password : str
    policies : list
    census_weights: dict
    policy_weights: dict

    def __init__(self, user, password=None):
        self.user = user
        self.password = password
        self.nation = api.nation(user, password=password)

        self.census_weights = copy.copy(weights_by_world_spread)
        self.policy_weights = dict()
        self.load_policies()

    def load_policies(self):
        """ Retrieves the nation's policies from nationstates api """
        policies = self.nation.get_shards("policies").policies.policy
        self.policies = [p.name for p in (policies if isinstance(policies, list) else [policies,])]

    def adjust_weights(self, census:dict=dict(), policy:dict=dict()):
        """ 1) Adjusts the current census_weights (default is weights_by_world_spread) by custom values in the following format:
            census = {0 : ("Nudity",), -1 : ("Death Rate", "Taxation"), 3: ("Civil Rights",)}
            This makes the solver ignore Nudity, minimise Death Rate and Taxation, and weigh Civil Rights more in its calclation of scores
            2) Sets the policy weights. For example:
            policy = {"No Internet": -10}
            would lower an outcome's score by 10 if it adds this policy"""
        for adjustment in census:
            for c_name in census[adjustment]:
                c_id = trotterdam.name_to_id[c_name]
                self.census_weights[c_id] *= adjustment
        self.policy_weights = policy
    
    def calc_outcome_score(self, outcome:trotterdam.Outcome):
        """ Calculates an outcome score according to census_weights and policy_weights """
        score = 0
        for c_id, change in outcome.census_changes.items():
            score += change * self.census_weights[c_id]
        for policy, change in outcome.policy_changes.items():
            if policy not in self.policy_weights:
                continue
            if policy in self.policies and change.value > 0:
                continue # can't add a policy if you already have it
            if policy not in self.policies and change.value < 0:
                continue # can't remove a policy if you don't have it
            score += self.policy_weights[policy] * change.value
        return score
    
    def solve_issue(self, issue, log = True):
        """ Solves an issue and returns option picked, outcome """
        if issue.id in trotterdam.unhandlable:
            return -1, None
        trotterdam_issue = trotterdam.Issue(issue.id)
        if not trotterdam_issue.table:
            if log:
                print("Was unable to load Trotterdam page for Issue #{}".format(issue.id))
            return -1, None

        option_scores = dict()
        for option in issue.option:
            option_id = int(option.id)
            # special cases where trotterdam options do not correspond to api options:
            if issue.id == '144' and option_id == 2:
                option_scores[option_id] = self.calc_outcome_score(trotterdam_issue.outcomes[1])
            elif issue.id == '906' and option_id == 4:
                option_scores[option_id] = self.calc_outcome_score(trotterdam_issue.outcomes[3])
            elif issue.id == '1187' and option_id == 3:
                option_scores[option_id] = self.calc_outcome_score(trotterdam_issue.outcomes[2])
            # general case:
            else:
                option_scores[option_id] = self.calc_outcome_score(trotterdam_issue.outcomes[option_id])
        best_option = max(option_scores, key=option_scores.get)

        if  int(issue.id) in skip_issues or option_scores[best_option] <= 0:
            """ Dissmisses an issue if it is in skipp_issues list or based on the score treshold """
            self.nation.command("issue", issue=issue.id, option=-1)	
            if log:	
                print("Dismissed issue #{}. All options are bad or the issue is in the skip list.".format(issue.id))	
            return -1, None	
        else:
            response = self.nation.pick_issue(issue.id, best_option).issue
            rankings = response.rankings.rank if "rankings" in response else []
            new_policies = response.new_policies.policy if "new_policies" in response else []
            removed_policies = response.removed_policies.policy if "removed_policies" in response else []

            outcome = trotterdam.Outcome()
            outcome.census_changes = {
                int(rank.id): float(rank.change)
                for rank in (rankings if isinstance(rankings, list) else [rankings,])
            }
            outcome.policy_changes = dict()
            for p in (new_policies if isinstance(new_policies, list) else [new_policies,]):
                outcome.policy_changes[p.name] = trotterdam.PolicyChange.ADDS
            for p in (removed_policies if isinstance(removed_policies, list) else [removed_policies,]):
                outcome.policy_changes[p.name] = trotterdam.PolicyChange.REMOVES

            if log:
                print(
                    "Picked option {} for issue #{}. This gave a score increase of {:.6f} (prediction was {:.6f})"
                        .format(best_option, issue.id, self.calc_outcome_score(outcome), option_scores[best_option])
                )
            for p in (new_policies if isinstance(new_policies, list) else [new_policies,]):
                self.policies.append(p.name)
                if log:
                    print("-> This added the policy '{}'".format(p.name))
            for p in (removed_policies if isinstance(removed_policies, list) else [removed_policies,]):
                self.policies.remove(p.name)
                if log:
                    print("-> This removed the policy '{}'".format(p.name))
            
            return best_option, outcome
    
    def solve_issues(self, log = True):
        """ Solves all issues """
        if not self.password:
            raise ValueError("Can't solve issues if the CensusMaximizer isn't initialised with a password")

        if log:
            print("Solving issues for {}".format(self.user))

        issues = self.nation.get_shards("issues").issues
        if not issues:
            if log:
                print("No issues")
        else:
            issues = issues.issue
            if not isinstance(issues, list): # only one issue
                issues = [issues,]
            for issue in issues:
                option_picked, outcome = self.solve_issue(issue, log = log)
            print("{} is now gloriously issue-free".format(self.user))
    
    def census_score_history(self, scales=None):
        """ Returns the history of weighted census scores for the nation. Return format is (timestamp, scores)
            where timestamp is a list of unix timestamp and scores a list of scores.
            these can be plotted using a module like matplotlib to view trends in the nation's score"""
        if not scales:
            scales = list(range(65)) + list(range(67, 80)) + [85] # Z-day and WA-stats as well as Residency removed as these make the data really unclear
        response = self.nation.get_shards(ns.Shard("census", scale=scales, mode="history"))
        min_ts = 1e100
        max_ts = 0
        for scale in response.census.scale:
            for point in scale.point:
                ts = int(point.timestamp)
                if ts < min_ts:
                    min_ts = ts
                if ts > max_ts:
                    max_ts = ts
        if max_ts == 0:
            return # something went wrong
        x = np.arange(min_ts, max_ts, 24*60**2)
        y = np.array([0. for o in x])
        for scale in response.census.scale:
            c_id = int(scale.id)
            # we must use interpolation as the timestamps aren't always the same for all scales
            interp_x = np.array([int(p.timestamp) for p in scale.point])
            interp_y = self.census_weights[c_id] * np.array([float(p.score) for p in scale.point])
            # Black market does something odd on 2019-11-19 (see https://www.nationstates.net/page=news/2019/index.html)
            # We need to adjust for this (the other changes are more negligible)
            if c_id == 79:
                i = 0
                while i < len(interp_x) and interp_x[i] < 1574164800:
                    i += 1
                interp_y[:i] /= 6 # this is an approximation and the exact number will vary for all nations. a jump will still be seen, but that is fine
            y += np.interp(x, interp_x, interp_y)
        return x, y
