from flask import Flask, render_template, request, jsonify
import requests
import os
from datetime import datetime

# Initialize the Flask application
app = Flask(__name__)

# Try to import gkeepapi, but make it optional
try:
    import gkeepapi
    KEEP_ENABLED = True
    keep = gkeepapi.Keep()
except ImportError:
    KEEP_ENABLED = False
    print("Google Keep integration disabled: gkeepapi not installed")

# Add these after Flask initialization
app.config['KEEP_USERNAME'] = os.getenv('KEEP_USERNAME', '')
app.config['KEEP_PASSWORD'] = os.getenv('KEEP_PASSWORD', '')

def init_keep():
    if not KEEP_ENABLED:
        return False
    try:
        keep.login(app.config['KEEP_USERNAME'], app.config['KEEP_PASSWORD'])
        return True
    except Exception as e:
        print(f"Failed to initialize Google Keep: {e}")
        return False

# Helper function to fetch top-starred repositories from GitHub API
def get_top_starred_repos(language, topic, sort='stars'):
    """
    Fetches repositories from GitHub based on language, topic, and search criteria.
    
    Args:
        language (str): Programming language (e.g., 'python')
        topic (str): Search term for topic, description, or name
        sort (str): Sort criterion ('stars', 'forks', 'updated')
    
    Returns:
        list: List of repository data, or empty list if request fails
    """
    # Create a more comprehensive search query
    query_parts = []
    
    if language:
        query_parts.append(f"language:{language}")
    
    # Search in name, description, topics, and readme
    if topic:
        topic_terms = topic.replace(',', ' ').split()
        for term in topic_terms:
            query_parts.append(f'"{term}" in:name,description,topics,readme')
    
    query = ' '.join(query_parts)
    
    # Remove per_page limit to get all results (GitHub API max is 100 per page)
    url = f"https://api.github.com/search/repositories?q={query}&sort={sort}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        # Add your GitHub token for higher rate limits
        # "Authorization": "token YOUR_GITHUB_TOKEN"
    }
    
    all_repos = []
    try:
        # Implement pagination to get all results
        page = 1
        while True:
            page_url = f"{url}&page={page}"
            response = requests.get(page_url, headers=headers)
            
            if response.status_code != 200:
                break
                
            data = response.json()
            repos = data.get("items", [])
            
            if not repos:
                break
                
            all_repos.extend(repos)
            
            # Check if we've reached the last page
            if len(repos) < 100:  # GitHub's max items per page
                break
                
            page += 1
            
            # Optional: Add a reasonable limit to avoid too many requests
            if page > 10:  # This will fetch up to 1000 repositories
                break
            
    except requests.exceptions.RequestException:
        return []
    
    # Enhance repository data with additional information
    for repo in all_repos:
        repo['topics'] = repo.get('topics', [])
        repo['description'] = repo.get('description', 'No description available')
        repo['language'] = repo.get('language', 'Not specified')
        repo['search_relevance'] = _calculate_relevance(repo, topic)
    
    # Sort results by search relevance and then by the specified sort criterion
    all_repos.sort(key=lambda x: (-x['search_relevance'], -x[sort.replace('stars', 'stargazers_count')]))
    
    return all_repos

def _calculate_relevance(repo, search_term):
    """
    Calculate search relevance score for a repository.
    """
    score = 0
    search_terms = search_term.lower().split()
    
    # Check name relevance
    for term in search_terms:
        if term in repo['name'].lower():
            score += 3
    
    # Check description relevance
    if repo['description']:
        for term in search_terms:
            if term in repo['description'].lower():
                score += 2
    
    # Check topics relevance
    for term in search_terms:
        if term in [topic.lower() for topic in repo.get('topics', [])]:
            score += 2
    
    return score

# Helper function to fetch details of a specific repository
def get_repo_details(owner, repo):
    """
    Fetches detailed information about a specific GitHub repository.
    
    Args:
        owner (str): Repository owner's username
        repo (str): Repository name
    
    Returns:
        dict: Repository details, or None if not found or request fails
    """
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except requests.exceptions.RequestException:
        return None

# Helper function to fetch recent events for a specific repository
def get_repo_events(owner, repo):
    """
    Fetches recent events for a specific GitHub repository.
    
    Args:
        owner (str): Repository owner's username
        repo (str): Repository name
    
    Returns:
        list: List of event data, or empty list if request fails
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/events"
    headers = {"Accept": "application/vnd.github.v3+json"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            return []
    except requests.exceptions.RequestException:
        return []

# Route to serve the main page
@app.route("/", methods=["GET", "POST"])
def index():
    """
    Renders the main page with search results and repository details.
    """
    results = []
    if request.method == "POST":
        language = request.form.get("language", "")
        topic = request.form.get("topic", "")
        sort = request.form.get("sort", "stars")
        if topic:  # Allow searching without specifying language
            results = get_top_starred_repos(language, topic, sort)
    return render_template("index.html", results=results)

# API endpoint to search for repositories
@app.route("/api/search", methods=["POST"])
def search():
    """
    Handles search requests for top-starred repositories based on user input.
    
    Expects form data:
        language (str): Programming language
        topic (str): Topic tag
        sort (str, optional): Sort criterion (defaults to 'stars')
    
    Returns:
        JSON: List of repository data
    """
    language = request.form.get("language")
    topic = request.form.get("topic")
    sort = request.form.get("sort", "stars")
    results = get_top_starred_repos(language, topic, sort)
    return jsonify(results)

# API endpoint to fetch repository details and events
@app.route("/api/repo/<owner>/<repo>", methods=["GET"])
def repo_details(owner, repo):
    """
    Fetches details and events for a specific repository.
    
    Args:
        owner (str): Repository owner's username
        repo (str): Repository name
    
    Returns:
        JSON: Dictionary with 'details' and 'events', or error message with 404 status
    """
    details = get_repo_details(owner, repo)
    events = get_repo_events(owner, repo)
    if details:
        return jsonify({"details": details, "events": events})
    else:
        return jsonify({"error": "Repository not found"}), 404

# Modify the bookmark route to handle both Keep and local storage
@app.route("/api/bookmark", methods=["POST"])
def bookmark_repo():
    """
    Saves a repository to local storage.
    """
    try:
        data = request.json
        repo_url = data.get('url')
        repo_name = data.get('name')
        repo_description = data.get('description')
        
        note_content = f"""
Repository: {repo_name}
URL: {repo_url}
Description: {repo_description}
Bookmarked on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """

        # Save to local file
        bookmarks_dir = os.path.join(os.path.dirname(__file__), 'bookmarks')
        os.makedirs(bookmarks_dir, exist_ok=True)
        
        filename = os.path.join(bookmarks_dir, f"{repo_name}.txt")
        with open(filename, 'w') as f:
            f.write(note_content)
        
        return jsonify({
            "success": True, 
            "message": "Repository bookmarked successfully",
            "storage": "Local file"
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# Update the initialization
if __name__ == "__main__":
    app.run(debug=True)