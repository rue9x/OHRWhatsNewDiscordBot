#!/usr/bin/env python3

import os
import posixpath
import re
import urllib.request
import configparser
import difflib

def parse_items(lines, unwrap = True):
    """Combine lines into items, which are either header lines or blocks starting with *.
    If unwrap, returns a list of long lines (ending in newlines if lines does),
    otherwise returns a list of strings containing multiple newlines."""
    items = []
    blankline = True
    for line in lines:
        stripped = line.strip()
        if stripped == '':
            blankline = True
            continue
        if blankline or stripped.startswith('*'):
            items.append(line)
        else:
            if unwrap:
                items[-1] = items[-1].rstrip()
                if not items[-1].endswith('-'):
                    items[-1] += ' '
                items[-1] += line.lstrip()
            else:
                items[-1] = items[-1] + line
        blankline = False
    return items

def pairwise(iterable):
    """Same as itertools.pairwise (Python 3.10+):
    Return successive overlapping pairs taken from the input iterable."""
    #return zip(iterable, iterable[1:])
    iterable = iter(iterable)
    prev = next(iterable)
    for item in iterable:
        yield prev, item
        prev = item

def compare_release_notes(old_notes, new_notes, newest_only = False, diff = True) -> str:
    '''
    Takes old_notes and new_notes, paths to two versions of whatsnew.txt
    (can also be used with IMPORTANT-nightly.txt).
    Returns a diff of added/removed lines, plus section headers above a changed line.
    Also unwraps lines, removes blanks, and readds blanks before sections.

    newest_only: Only show changes to the latest release
    diff: Display +/-/? lines not just added lines
    '''
    # Read the contents of the old release notes
    with open(old_notes, 'r') as old_file:
        old_items = parse_items(old_file.readlines())

    # Read the contents of the new release notes
    with open(new_notes, 'r') as new_file:
        new_items = parse_items(new_file.readlines())

    # A pattern to match release headers: no indentation and a [release name]
    release_pattern = r"\S.*\[.+\]"
    indent_pattern = re.compile(' *')

    def indentation(line):
        "Number of indenting spaces"
        line = line.lstrip('\n')  # Remove extra space before a header
        line = line[2:]  # Remove the tag
        return indent_pattern.match(line).end()  # Always matches

    releases = 0  # How many releases we've seen
    retval = ""
    # The section headers that are above the current item which haven't yet been added to retval
    header_stack = []

    diffitems = list(difflib.ndiff(old_items, new_items, charjunk=lambda x: x in " _{}.[]"))
    diffitems_set = set(diffitems)

    for ditem, nextditem in pairwise(diffitems):
        # diffitem starts with "  ", "+ ", "- " or "? "
        tag = ditem[0]
        # if tag == '?':
        #     continue

        item = ditem[2:]
        indent = indentation(ditem)
        next_indent = indentation(nextditem)

        # Prune items from the header_stack
        while header_stack and indentation(header_stack[-1]) >= indent:
            header_stack.pop()

        if diff:
            edit_item = ditem
        else:
            edit_item = item
        if indent == 0 or "***" in edit_item: # Add some extra formatting for new sections (which start with ***)
            edit_item = "\n" + edit_item

        if tag in "+-?":
            # Add delayed headers
            retval += ''.join(header_stack)
            header_stack = []
        elif next_indent > indent:
            if len(edit_item) > 80:
                # Sometimes items which are new features have sub-bullet points but are
                # quite long, so limit the length of header lines
                edit_item = edit_item[:80] + "...\n"
            header_stack.append(edit_item)

        # Show only the first release in the file (the new/upcoming update)
        if newest_only and re.match(release_pattern, item):
           releases += 1
           if releases > 1:
               return retval

        # Ignore items which are moved unchanged
        if tag == '+' and ('- ' + item) in diffitems_set:
            tag = ' '
        if tag == '-' and ('+ ' + item) in diffitems_set:
            tag = ' '

        if diff:
            if tag == '?':
                edit_item = ' ' + edit_item[1:]

            if tag in "-+?":
                retval += edit_item
        else:
            if tag in '+':
                retval += edit_item

    return retval.lstrip('\n')

def save_from_url(url, file_path, cache = False):
    ''' 
    Takes a url (preferably a whatsnew.txt) and file_path (where to save it).
    '''
    if cache and os.path.isfile(file_path):
        print(f"Already downloaded {url} as {file_path}")
        return

    try:
        print(f"Fetching {url}")
        urllib.request.urlretrieve(url, file_path)
        print(f"File downloaded successfully and saved as {file_path}")
    except Exception as e:
        print(f"Error occurred while downloading the file: {str(e)}")
        raise

def compare_urls(oldurl, newurl):
    "Fetch old and new whatsnew.txt and return a description of the changes"

    old_release_notes_file = 'release.txt'
    new_release_notes_file = 'whatsnew.txt'
    save_from_url(oldurl, old_release_notes_file)
    save_from_url(newurl, new_release_notes_file)

    return compare_release_notes(old_release_notes_file, new_release_notes_file)

class EngineBuild:
    def __init__(self, name, url, svn_rev, build_date = 0, important = False):
        self.name = name
        self.url = url
        self.svn_rev = int(svn_rev)
        self.build_date = int(build_date)
        self.important = important

    def label(self):
        return self.name + ": r" + str(self.svn_rev)

    def __str__(self):
        return self.label() + " " + self.url

def url_changed(url, path):
    "Download url to path, overwriting and returning whether it differs from any existing file."
    if not os.path.isfile(path):
        save_from_url(url, path)
        return True

    save_from_url(url, path + '.new')
    with open(path, 'r') as f1:
        with open(path + '.new', 'r') as f2:
            ret = f1.read() != f2.read()

    os.rename(path + '.new', path)
    return ret

def get_builds(nightly_check_url, path = 'nightly-check.ini', cache = True):
    """Download nightly_check_url to path if it hasn't been already and parse it,
    returning a list of EngineBuilds.
    Caches download by default, intended to be called after url_changed()."""

    save_from_url(nightly_check_url, path, cache = cache)

    nightly_dir = posixpath.split(nightly_check_url)[0] + '/'

    config = configparser.ConfigParser()
    config.read(path)

    def check_build(buildname, os, player_ext, base, suffix, nightly_ext, important = False):
        player_file = f'ohrrpgce-player-{os}-wip-{suffix}{player_ext}'
        nightly_url = nightly_dir + f'{base}-wip-{suffix}{nightly_ext}'

        if player_file in config:
            section = config[player_file]
            build = EngineBuild(buildname, nightly_url, section['svn_rev'], section['build_date'], important)
            ret.append(build)

            # Special case: add Debian
            if os == 'linux' and suffix == 'x86_64':
                d = section['build_date']
                datecode = '%s-%s-%s' % (d[:4], d[4:6], d[6:])
                nightly_url = nightly_dir + f'ohrrpgce_{datecode}.wip-{section["svn_rev"]}_amd64.deb'
                build = EngineBuild('Debian amd64', nightly_url, section['svn_rev'], section['build_date'], False)
                ret.append(build)

        else:
            print(f"warning: {player_file} missing from nightly-check.ini")

    ret = []
    check_build('Windows',      'win',   '.zip',    'ohrrpgce-win',   'sdl2',   '.zip',     True)
    check_build('Win 95',       'win',   '.zip',    'ohrrpgce-win',   'win95',  '.zip')
    check_build('Linux x86_64', 'linux', '.zip',    'ohrrpgce-linux', 'x86_64', '.tar.bz2', True)  # plus Debian
    check_build('Linux x86',    'linux', '.zip',    'ohrrpgce-linux', 'x86',    '.tar.bz2')
    check_build('Mac x86_64',   'mac',   '.tar.gz', 'OHRRPGCE',       'x86_64', '.dmg',     True)
    check_build('Mac x86',      'mac',   '.tar.gz', 'OHRRPGCE',       'x86',    '.dmg')
    return ret


if __name__ == '__main__':
    # For testing
    print(compare_urls("https://hamsterrepublic.com/ohrrpgce/whatsnew.txt",
                       "https://raw.githubusercontent.com/ohrrpgce/ohrrpgce/wip/whatsnew.txt"))
