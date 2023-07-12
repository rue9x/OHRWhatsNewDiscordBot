#!/usr/bin/env python3

import os
import re
import urllib.request
import difflib

def parse_items(lines, unwrap = True):
    """Combine lines into items, which either header lines or blocks starting with *.
    If unwrap, returns a list of long lines (ending in newlines if lines does),
    otherwise returns a list of strings containing multiple newlines."""
    items = []
    for line in lines:
        stripped = line.strip()
        if stripped == '':
            continue
        # "Highlights" is a special case missing a '*'
        if not line.startswith(' ') or stripped.startswith('*') or stripped == 'Highlights:':
            items.append(line)
        else:
            if unwrap:
                items[-1] = items[-1].rstrip()
                if not items[-1].endswith('-'):
                    items[-1] += ' '
                items[-1] += line.lstrip()
            else:
                items[-1] = items[-1] + line
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

def compare_release_notes(old_notes, new_notes):
    '''
    Takes old_notes and new_notes, paths to two versions of whatsnew.txt.
    Returns (as a string) only those lines in new_notes for the newest release
    that aren't in old_notes, or which are section headers.
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

        edit_item = ditem
        if "***" in edit_item: # Add some extra formatting for new sections (which start with ***)
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
        #if re.match(release_pattern, item):
        #    releases += 1
        #    if releases > 1:
        #        return retval

        # Ignore items which are moved unchanged
        if tag == '+' and ('- ' + item) in diffitems_set:
            tag = ' '
        if tag == '-' and ('+ ' + item) in diffitems_set:
            tag = ' '

        if tag == '?':
            edit_item = ' ' + edit_item[1:]

        if tag in "-+?":
            retval += edit_item

    return retval

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
    save_from_url(oldurl, old_release_notes_file, True)
    save_from_url(newurl, new_release_notes_file, True)

    return compare_release_notes(old_release_notes_file, new_release_notes_file)

if __name__ == '__main__':
    # For testing
    print(compare_urls("https://hamsterrepublic.com/ohrrpgce/whatsnew.txt",
                       "https://raw.githubusercontent.com/ohrrpgce/ohrrpgce/wip/whatsnew.txt"))
