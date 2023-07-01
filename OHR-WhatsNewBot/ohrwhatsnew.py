import re
import urllib.request

def compare_release_notes(old_notes, new_notes):
    '''
    Takes old_notes (previous release's whatsnew.txt) and the new_notes (nightly whatsnew.txt).
    Returns a list of lines displaying only whats new in the nightly release.
    '''
    # Read the contents of the old release notes
    with open(old_notes, 'r') as old_file:
        old_lines = old_file.readlines()

    # Read the contents of the new release notes
    with open(new_notes, 'r') as new_file:
        new_lines = new_file.readlines()

    # A pattern to match release headers: no indentation and a [release name]
    release_pattern = r"\S.*\[.+\]"

    releases = 0  # How many releases we've seen
    retval = ""

    for line in new_lines:  
        edit_line = line.strip('\n')
        keep = False
        if "***" in edit_line: # Add some extra formatting for new sections (which start with ***)
            edit_line = "\n\n"+edit_line
            keep = True

        match = re.match(release_pattern, line)
        if match != None:
            keep = True
            releases += 1
            if releases > 1:
                # Show only the first release in the file (the new/upcoming update)
                return retval

        if keep or line not in old_lines:
            # Compare the old release with the new release. If it's new, add it.
            retval = retval + edit_line + "\n"

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
