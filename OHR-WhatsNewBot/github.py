import json
import os
import posixpath
import re
import requests
import time

verbose = True
HEADLINE_LENGTH = 120


def format_date(t) -> str:
    "Format time since epoch in ISO 8601 format, as used by GitHub APIs"
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))

def parse_date(t) -> float:
    "Parse time in ISO 8601 format into a tuple"
    return time.mktime(time.strptime(t, "%Y-%m-%dT%H:%M:%S%z"))

def trim_str(s, maxlen):
    if len(s) > maxlen:
        return s[:maxlen - 3] + "..."
    return s


class GitHubError(Exception):
    pass


class GitCommit:
    "A summary of info from a git commit returned from the GitHub API as a JSON object"

    sha = None
    svn_rev = 0
    author = None
    url = None
    message = None   # Excluding the git-svn line
    headline = None  # First line of the message, trimmed
    date = None      # Committer time, in seconds

    def __init__(self, commit: dict, _load_from_dict: dict = None):
        "Parses one item from a JSON list of commits from GitHub"
        if _load_from_dict:
            self.__dict__.update(_load_from_dict)
            return

        self.sha = commit['sha']

        self.message = commit['commit']['message']
        msg_lines = self.message.splitlines()
        if msg_lines[-1].startswith('git-svn-id: '):
            self.svn_rev = int(re.search('@([0-9]+) ', msg_lines[-1]).group(1))
            del msg_lines[-1]
            self.message = '\n'.join(msg_lines).strip()
        self.headline = trim_str(msg_lines[0], HEADLINE_LENGTH)
        self.author = commit['commit']['author']['name']
        self.date = parse_date(commit['commit']['committer']['date'])
        self.url = commit['html_url']
        # Trim the SHA in the URL to 8 chars
        head, sha = posixpath.split(self.url)
        if sha == self.sha:
            self.url = head + '/' + sha[:8]

    def rev(self) -> str:
        "svn or git commit for human consumption"
        if self.svn_rev:
            return 'r' + str(self.svn_rev)
        return self.sha[:6]

    def short_format(self, hyperlink = False):
        if hyperlink:
            return f"[{self.rev()}]({self.url}): {self.headline} [{self.author}]"
        else:
            return f"{self.rev()}: {self.headline} [{self.author}]"

    def __str__(self):
        return self.short_format()

    def format(self):
        ret = f"{self.rev()}  [{self.author}]  {time.ctime(self.date)}\n"
        ret += f"{self.url}\n"
        ret += ('-' * 20) + "\n"
        ret += self.message
        return ret


class GitHubRepo:
    "Interface with the GitHub API"

    def __init__(self, user_repo):
        "user_repo should be a username/reponame"
        self.user_repo = user_repo
        self.repo_url = "https://api.github.com/repos/" + user_repo
        self.svn_revs = {}  # Maps svn revision -> git sha for seen commits
        self.load_svn_revs()

    def load_svn_revs(self):
        "Load .svn_revs from file"
        self.svn_revs_file = 'svn_revs_' + self.user_repo.replace('/', '_') + '.json'
        if os.path.isfile(self.svn_revs_file):
            print("Loading " + self.svn_revs_file)
            with open(self.svn_revs_file, 'r') as fi:
                # json keys can't be ints, they are converted to strings, so convert back
                self.svn_revs = dict((int(k),v) for k,v in json.load(fi).items())

    def save_svn_revs(self):
        "Save .svn_revs to file"
        with open(self.svn_revs_file, 'w') as fo:
            fo.write(json.dumps(self.svn_revs, sort_keys = True, indent = 1))

    def decode_rev(self, rev):
        """Convert svn revisions to git shas if it's a recent, recognised revision.
        Throws KeyError if couldn't look it up, ValueError if invalid.
        Passes through shas."""
        if rev.startswith('r'):
            return self.svn_revs[int(rev[1:])]
        if re.fullmatch("[0-9a-f]*", rev) and len(rev) >= 4:
            return rev
        raise ValueError(rev)

    def check_rate_limit(self):
        rate_limit = self.get_json("https://api.github.com/rate_limit")
        print(rate_limit)
        reset_wait = rate_limit["resources"]["core"]["reset"] - time.time()
        remaining = rate_limit["resources"]["core"]["remaining"]
        print("Github rate_limit: %d requests left in next %d min" % (remaining, reset_wait / 60))

    def blob_url(self, ref, filepath):
        "URL to download a file"
        return f"https://raw.githubusercontent.com/{self.user_repo}/{ref}/{filepath}"

    def get(self, url, params = {}, headers = {}) -> requests.Response:
        """requests.get() wrapper. params are query parameters to add."""
        if url.startswith("/"):
            url = self.repo_url + url
        #params["access_token"] = github_token
        resp = requests.get(url, params = params, headers = headers)
        if verbose:
            print(url, "Status:", resp.status_code)
        if 'x-ratelimit-remaining' in resp.headers:
            remaining = int(resp.headers['x-ratelimit-remaining'])
            reset_wait = int(resp.headers['x-ratelimit-reset']) - time.time()
            if verbose or remaining <= 0:
                print("Github ratelimit: %d requests left in next %d min" % (remaining, reset_wait / 60))
        return resp

    def get_json(self, url, params = {}, headers = {}):
        "Get url and parse as JSON, else raise GitHubError."
        resp = self.get(url, params, headers)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 422:
            # Not the only status code that means rate exceeded
            raise GitHubError("GitHub rate exceeded, or validation failed")
        elif resp.status_code == 404:
            raise GitHubError(resp.json()['message'])
        else:
            raise GitHubError("Unknown status code in reply %s\n%s" % (resp, resp.json()))

    def current_sha(self, ref):
        "Get sha of last commit to a branch or tag (to disambiguate, use 'heads/BRANCH' or 'tags/TAG')"
        resp = self.get('/commits/' + ref, headers = {'Accept': 'application/vnd.github.sha'})
        if resp.status_code == 200:
            return resp.text
        raise GitHubError(str(resp))

    def last_sha_touching(self, ref, path):
        "Returns sha for last commit touching a path"
        return self.last_commits(ref, 1, path)[0].sha

    def last_commits(self, ref, num = 40, touching_path = None, since: GitCommit = None):
        """"Get list of last `num` GitCommits to a branch/tag, optionally touching a file.
        num is limited to 100."""
        # Not equivalent to get('/commits/ + ref)
        since_date = None
        if since:
            since_date = format_date(since.date - 1)

        resp = self.get_json('/commits', {'sha': ref, 'path': touching_path, 'since': since_date, 'per_page': num})
        ret = []
        #print(f"/commits {ref} since {since_date} returned {len(resp)}")
        for jsoncommit in resp:
            commit = GitCommit(jsoncommit)
            if commit.svn_rev:
                self.svn_revs[commit.svn_rev] = commit.sha
            if since and commit.sha == since.sha:
                break
            ret.append(commit)
        #print(f" kept {len(ret)} commits")
        self.save_svn_revs()
        return ret


if __name__ == '__main__':
    # For testing
    repo = GitHubRepo("ohrrpgce/ohrrpgce")
    print(repo.current_sha('wip'))
    for commit in repo.last_commits('wip', 5, 'whatsnew.txt'):
        print('=' * 40)
        print(commit.format())
