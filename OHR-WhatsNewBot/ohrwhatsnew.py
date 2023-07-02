import re
import urllib.request

def parse_items(lines, unwrap = False):
    """Combine lines into items, which either header lines or blocks starting with *.
    If unwrap, returns a list of long lines (ending in newlines if lines does),
    otherwise returns a list of strings containing multiple newlines."""
    items = []
    for line in lines:
        stripped = line.strip()
        if stripped == '':
            continue
        if not line.startswith(' ') or stripped.startswith('*') or stripped == 'Highlights:':
            items.append(line)
        else:
            if unwrap:
                items[-1] = items[-1].rstrip() + ' ' + line.lstrip()
            else:
                items[-1] = items[-1] + line
    return items

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

    releases = 0  # How many releases we've seen
    retval = ""

    for item in new_items:
        edit_item = item.strip('\n')
        keep = False
        if "***" in edit_item: # Add some extra formatting for new sections (which start with ***)
            edit_item = "\n\n"+edit_item
            keep = True

        match = re.match(release_pattern, item)
        if match != None:
            keep = True
            releases += 1
            if releases > 1:
                # Show only the first release in the file (the new/upcoming update)
                return retval

        if keep or item not in old_items:
            # Compare the old release with the new release. If it's new, add it.
            retval += edit_item + "\n"

    return retval


def save_from_url(url, file_path):
    ''' 
    Takes a url (preferably a whatsnew.txt) and file_path (where to save it).
    '''
    try:
        urllib.request.urlretrieve(url, file_path)
        print(f"File downloaded successfully and saved as {file_path}")
    except Exception as e:
        print(f"Error occurred while downloading the file: {str(e)}")


def compare_urls(oldurl, newurl):
    "Fetch old and new whatsnew.txt and return a description of the changes"

    old_release_notes_file = 'release.txt'
    new_release_notes_file = 'nightly.txt'
    save_from_url(oldurl, old_release_notes_file)
    save_from_url(newurl, new_release_notes_file)

    return compare_release_notes(old_release_notes_file, new_release_notes_file)

if __name__ == '__main__':
    # For testing
    print(compare_urls("https://hamsterrepublic.com/ohrrpgce/whatsnew.txt",
                       "https://raw.githubusercontent.com/ohrrpgce/ohrrpgce/wip/whatsnew.txt"))
