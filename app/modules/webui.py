"""
WebUI module for AutoFilm
Provides a web interface to manage configurations and execute tasks
"""
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Any

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.core.config import settings
from app.modules.alist2strm.alist2strm import alist2strm, Alist2Strm
from app.modules.ani2alist.ani2alist import ani2alist, Ani2Alist


class ConfigUpdateRequest(BaseModel):
    config_data: Dict[str, Any]


class LoginRequest(BaseModel):
    username: str
    password: str


class TaskExecuteRequest(BaseModel):
    task_type: str  # "alist2strm", "ani2alist", "specific_project", "specific_ani", or "all"
    task_id: str = None  # 用于指定具体的 alist2strm 或 ani2alist 任务 ID


app = FastAPI(title="AutoFilm WebUI", version="1.0.0")

# Mount static files if we have them
static_dir = Path(__file__).parent.parent / "static"
if not static_dir.exists():
    static_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Templates directory
templates_dir = Path(__file__).parent.parent / "templates"
if not templates_dir.exists():
    templates_dir.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(templates_dir))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main page showing configuration editor"""
    try:
        with settings.CONFIG.open("r", encoding="utf-8") as file:
            config_content = yaml.safe_load(file)
    except FileNotFoundError:
        config_content = {}
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "config": json.dumps(config_content, indent=2, ensure_ascii=False),
        "tasks": ["alist2strm", "ani2alist"]
    })


@app.post("/api/login")
async def login(request: LoginRequest):
    """Login to WebUI"""
    web_config = settings.WEB_CONFIG
    if request.username == web_config["username"] and request.password == web_config["password"]:
        # In a real app, generate a JWT token here
        return {"token": "authenticated-session-token"}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/api/logout")
async def logout():
    """Logout from WebUI"""
    # In our simple session implementation, we just invalidate the client-side token
    # The actual invalidation happens on the frontend by clearing the stored token
    return {"message": "Logged out successfully"}


@app.get("/api/config")
async def get_config():
    """Get current configuration"""
    try:
        with settings.CONFIG.open("r", encoding="utf-8") as file:
            config_content = yaml.safe_load(file)
        return JSONResponse(content=config_content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")


@app.post("/api/config")
async def update_config(request: ConfigUpdateRequest):
    """Update configuration"""
    try:
        # Validate the config data structure before saving
        config_data = request.config_data
        
        # Ensure required keys exist
        if "Alist2StrmList" not in config_data:
            config_data["Alist2StrmList"] = []
        if "Ani2AlistList" not in config_data:
            config_data["Ani2AlistList"] = []
        if "TelegramBot" not in config_data:
            config_data["TelegramBot"] = {}
        
        # Write the new configuration to file
        with settings.CONFIG.open("w", encoding="utf-8") as file:
            yaml.dump(config_data, file, default_flow_style=False, allow_unicode=True)
        
        return {"message": "Configuration updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating config: {str(e)}")


@app.post("/api/task/execute")
async def execute_task(request: TaskExecuteRequest):
    """Execute specific task"""
    try:
        executed_task_name = request.task_type

        if request.task_type == "alist2strm":
            # Run all the alist2strm modules
            await alist2strm()
            executed_task_name = "all alist2strm"
        elif request.task_type == "ani2alist":
            # Run the ani2alist module
            await ani2alist()
            executed_task_name = "all ani2alist"
        elif request.task_type == "all":
            # Run both modules
            await asyncio.gather(
                alist2strm(),
                ani2alist()
            )
            executed_task_name = "all tasks"
        elif request.task_type in ("specific_project", "specific_alist"):
            # Execute a specific Alist2Strm task by ID
            if not request.task_id:
                raise HTTPException(status_code=400, detail="Task ID is required for specific task execution")

            # Read the config to find the specific task
            with settings.CONFIG.open("r", encoding="utf-8") as file:
                config_content = yaml.safe_load(file)

            # Find the task with the given ID
            task_found = False
            if "Alist2StrmList" in config_content:
                for task_config in config_content["Alist2StrmList"]:
                    if task_config.get("id") == request.task_id:
                        # Found the task, create and run it
                        alist_task = Alist2Strm(**task_config)
                        await alist_task.run()
                        executed_task_name = task_config.get("id") or request.task_id
                        task_found = True
                        break

            if not task_found:
                raise HTTPException(status_code=404, detail=f"Task with ID '{request.task_id}' not found")
        elif request.task_type == "specific_ani":
            # Execute a specific Ani2Alist task by ID
            if not request.task_id:
                raise HTTPException(status_code=400, detail="Task ID is required for specific task execution")

            # Read the config to find the specific task
            with settings.CONFIG.open("r", encoding="utf-8") as file:
                config_content = yaml.safe_load(file)

            # Find the task with the given ID
            task_found = False
            if "Ani2AlistList" in config_content:
                for task_config in config_content["Ani2AlistList"]:
                    if task_config.get("id") == request.task_id:
                        # Found the task, create and run it
                        ani_task = Ani2Alist(**task_config)
                        await ani_task.run()
                        executed_task_name = task_config.get("id") or request.task_id
                        task_found = True
                        break

            if not task_found:
                raise HTTPException(status_code=404, detail=f"Ani2Alist task with ID '{request.task_id}' not found")
        else:
            raise HTTPException(status_code=400, detail="Invalid task type")

        return {"message": f"Task '{executed_task_name}' executed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing task: {str(e)}")


@app.get("/api/tasks")
async def get_tasks():
    """Get list of available tasks"""
    try:
        with settings.CONFIG.open("r", encoding="utf-8") as file:
            config_content = yaml.safe_load(file)
        
        alist_tasks = []
        if "Alist2StrmList" in config_content:
            for task in config_content["Alist2StrmList"]:
                alist_tasks.append({
                    "id": task.get("id"),
                    "source_dir": task.get("source_dir"),
                    "target_dir": task.get("target_dir")
                })
        
        ani_tasks = []
        if "Ani2AlistList" in config_content:
            for task in config_content["Ani2AlistList"]:
                ani_tasks.append({
                    "id": task.get("id"),
                    "target_dir": task.get("target_dir")
                })
        
        return {
            "alist2strm_tasks": alist_tasks,
            "ani2alist_tasks": ani_tasks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching tasks: {str(e)}")


@app.get("/api/status")
async def get_status():
    """Get current status of the system"""
    # Import the scheduler from main here to avoid circular import during module loading
    from app.main import scheduler
    
    jobs = []
    if scheduler and scheduler.running:
        for job in scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": str(job.next_run_time)
            })
    
    return {
        "app_version": settings.APP_VERSION,
        "app_name": settings.APP_NAME,
        "scheduled_jobs": len(jobs),
        "jobs": jobs
    }


@app.get("/api/logs")
async def get_logs():
    """Get system logs"""
    try:
        log_file = settings.LOG
        if not log_file.exists():
            return {"logs": "Log file not found."}
        
        # Read the log file
        # To prevent huge payloads, we could limit size, but for now read all
        # as it's a local tool usually.
        with log_file.open("r", encoding="utf-8") as f:
            content = f.read()
            # Simple truncation if extremely large (e.g. > 1MB)
            if len(content) > 1000000:
                content = "...[logs truncated]...\n" + content[-1000000:]
            return {"logs": content}
    except Exception as e:
        return {"logs": f"Error reading logs: {str(e)}"}


# Create default template if it doesn't exist
template_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoFilm WebUI</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            border-bottom: 2px solid #007bff;
            padding-bottom: 10px;
        }
        .section {
            margin-bottom: 30px;
        }
        textarea {
            width: 100%;
            min-height: 300px;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-family: monospace;
            resize: vertical;
        }
        button {
            background-color: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            margin-right: 10px;
            margin-bottom: 10px;
        }
        button:hover {
            background-color: #0056b3;
        }
        button.execute {
            background-color: #28a745;
        }
        button.execute:hover {
            background-color: #218838;
        }
        button.task-button {
            background-color: #17a2b8;
        }
        button.task-button:hover {
            background-color: #138496;
        }
        button.ani-task-button {
            background-color: #fd7e14;
        }
        button.ani-task-button:hover {
            background-color: #e06b12;
        }
        .status-bar {
            background-color: #e9ecef;
            padding: 10px;
            border-radius: 4px;
            margin-top: 10px;
        }
        .form-group {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }
        .task-list {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 10px;
        }
        .task-section {
            margin-bottom: 20px;
        }
        .task-section h3 {
            border-bottom: 1px solid #ccc;
            padding-bottom: 5px;
            color: #495057;
        }
        .error-message {
            color: #dc3545;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>AutoFilm WebUI</h1>
        
        <div class="section">
            <h2>Configuration Editor</h2>
            <textarea id="config-editor">{{ config }}</textarea><br>
            <button onclick="saveConfig()">Save Configuration</button>
        </div>
        
        <div class="section">
            <h2>Execute Tasks</h2>
            <button class="execute" onclick="executeTask('alist2strm')">Run All Alist2Strm</button>
            <button class="execute" onclick="executeTask('ani2alist')">Run All Ani2Alist</button>
            <button class="execute" onclick="executeTask('all')">Run All Tasks</button>
        </div>
        
        <div class="section">
            <h2>Execute Specific Tasks</h2>
            <div class="task-section">
                <h3>Alist2Strm Tasks</h3>
                <div id="alist-task-buttons" class="task-list">
                    <!-- Alist2Strm task buttons will be loaded here -->
                    <p>Loading Alist2Strm tasks...</p>
                </div>
            </div>
            
            <div class="task-section">
                <h3>Ani2Alist Tasks</h3>
                <div id="ani-task-buttons" class="task-list">
                    <!-- Ani2Alist task buttons will be loaded here -->
                    <p>Loading Ani2Alist tasks...</p>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>System Status</h2>
            <div id="status" class="status-bar">Loading status...</div>
        </div>
    </div>

    <script>
        async function saveConfig() {
            const configText = document.getElementById('config-editor').value;
            
            try {
                const configData = JSON.parse(configText);
                
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({config_data: configData})
                });
                
                if (response.ok) {
                    alert('Configuration saved successfully!');
                } else {
                    const error = await response.json();
                    alert('Error: ' + error.detail || 'Failed to save configuration');
                }
            } catch (e) {
                alert('Invalid JSON format: ' + e.message);
            }
        }
        
        async function executeTask(taskType, taskId = null) {
            const payload = {task_type: taskType};
            if (taskId) {
                payload.task_id = taskId;
            }
            
            const response = await fetch('/api/task/execute', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
            
            if (response.ok) {
                const result = await response.json();
                alert(result.message);
            } else {
                const error = await response.json();
                alert('Error: ' + error.detail || 'Failed to execute task');
            }
        }
        
        async function loadTasks() {
            try {
                const response = await fetch('/api/tasks');
                if (response.ok) {
                    const tasks = await response.json();
                    
                    // Load Alist2Strm tasks
                    const alistTaskButtonsContainer = document.getElementById('alist-task-buttons');
                    alistTaskButtonsContainer.innerHTML = '';
                    
                    if (tasks.alist2strm_tasks && tasks.alist2strm_tasks.length > 0) {
                        tasks.alist2strm_tasks.forEach(task => {
                            const button = document.createElement('button');
                            button.className = 'task-button';
                            button.textContent = task.id;
                            button.title = `Source: ${task.source_dir} -> Target: ${task.target_dir}`;
                            button.onclick = () => executeTask('specific_project', task.id);
                            alistTaskButtonsContainer.appendChild(button);
                        });
                    } else {
                        alistTaskButtonsContainer.innerHTML = '<p>No Alist2Strm tasks configured</p>';
                    }
                    
                    // Load Ani2Alist tasks
                    const aniTaskButtonsContainer = document.getElementById('ani-task-buttons');
                    aniTaskButtonsContainer.innerHTML = '';
                    
                    if (tasks.ani2alist_tasks && tasks.ani2alist_tasks.length > 0) {
                        tasks.ani2alist_tasks.forEach(task => {
                            const button = document.createElement('button');
                            button.className = 'ani-task-button';
                            button.textContent = task.id;
                            button.title = `Target: ${task.target_dir}`;
                            button.onclick = () => executeTask('specific_ani', task.id);
                            aniTaskButtonsContainer.appendChild(button);
                        });
                    } else {
                        aniTaskButtonsContainer.innerHTML = '<p>No Ani2Alist tasks configured</p>';
                    }
                } else {
                    const error = await response.json();
                    document.getElementById('alist-task-buttons').innerHTML = 
                        `<p class="error-message">Error loading Alist2Strm tasks: ${error.detail || 'Failed to load tasks'}</p>`;
                    document.getElementById('ani-task-buttons').innerHTML = 
                        `<p class="error-message">Error loading Ani2Alist tasks: ${error.detail || 'Failed to load tasks'}</p>`;
                }
            } catch (error) {
                console.error('Error loading tasks:', error);
                document.getElementById('alist-task-buttons').innerHTML = 
                    `<p class="error-message">JavaScript error loading Alist2Strm tasks: ${error.message}</p>`;
                document.getElementById('ani-task-buttons').innerHTML = 
                    `<p class="error-message">JavaScript error loading Ani2Alist tasks: ${error.message}</p>`;
            }
        }
        
        async function loadStatus() {
            try {
                const response = await fetch('/api/status');
                if (response.ok) {
                    const status = await response.json();
                    document.getElementById('status').innerHTML = 
                        `<strong>App:</strong> ${status.app_name} v${status.app_version}<br>
                         <strong>Scheduled Jobs:</strong> ${status.scheduled_jobs}<br>
                         <strong>Jobs:</strong> ${status.jobs.map(j => j.name).join(', ') || 'None'}`;
                } else {
                    const error = await response.json();
                    document.getElementById('status').innerHTML = 
                        `<p class="error-message">Error loading status: ${error.detail || 'Failed to load status'}</p>`;
                }
            } catch (error) {
                console.error('Error loading status:', error);
                document.getElementById('status').innerHTML = 
                    `<p class="error-message">JavaScript error loading status: ${error.message}</p>`;
            }
        }
        
        // Load tasks and status on page load and refresh every 30 seconds
        window.onload = function() {
            loadTasks();
            loadStatus();
            setInterval(loadTasks, 30000);
            setInterval(loadStatus, 30000);
        };
    </script>
</body>
</html>
"""

template_path = templates_dir / "index.html"
if not template_path.exists():
    with open(template_path, "w", encoding="utf-8") as f:
        f.write(template_content)