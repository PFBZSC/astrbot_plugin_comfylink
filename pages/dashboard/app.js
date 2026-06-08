// 引入 AstrBot 桥接对象
const bridge = window.AstrBotPluginPage;

const Utils = {
  generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      const r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  },
  showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.remove(); }, 3000);
  },
  showConfirm(message, onConfirm) {
    const dialog = document.getElementById('confirmModal');
    document.getElementById('dialogMessage').textContent = message;
    const handleConfirm = () => { dialog.close(); cleanup(); onConfirm(); };
    const handleCancel = () => { dialog.close(); cleanup(); };
    const cleanup = () => {
      document.getElementById('dialogBtnConfirm').removeEventListener('click', handleConfirm);
      document.getElementById('dialogBtnCancel').removeEventListener('click', handleCancel);
    };
    document.getElementById('dialogBtnConfirm').addEventListener('click', handleConfirm);
    document.getElementById('dialogBtnCancel').addEventListener('click', handleCancel);
    dialog.showModal();
  },
  deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
  }
};

const Store = {
  currentTab: 'coreConfig',
  data: {
    core: [],
    prompt: {},
    telegram: {}
  },
  workflows: {},
  editingCoreIndex: -1,
  editingCoreData: null
};

const App = {
  async init() {
    // 1. 确保 SDK 已经就绪
    await bridge.ready();

    this.bindEvents();

    // 2. 从后端加载持久化的数据
    await this.loadDataFromServer();
    this.renderView();
  },

  async loadDataFromServer() {
    try {
      const res = await bridge.apiGet("get_all");
      if (res) {
        if (res.core) Store.data.core = res.core;
        // 如果有 prompt 和 telegram 也可以在这里赋值
        if (res.workflows) Store.workflows = res.workflows;
      }
    } catch (err) {
      Utils.showToast("从后端获取数据失败", "error");
    }
  },


  bindEvents() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
        e.target.classList.add('active');
        Store.currentTab = e.target.dataset.target;
        document.getElementById(Store.currentTab).classList.add('active');
        this.renderView();
      });
    });

    document.getElementById('btnExport').addEventListener('click', () => this.exportJSON());
    document.getElementById('btnImport').addEventListener('click', () => document.getElementById('fileInput').click());
    document.getElementById('fileInput').addEventListener('change', (e) => this.importJSON(e));
  },

  // =====================
  // Workflow 上传与后端对接
  // =====================
  uploadWorkflow(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (e) => {
      try {
        // 1. 直接在前端把 JSON 文件读成对象
        const parsed = JSON.parse(e.target.result);

        // 2. 复用已经跑通的 save_item 接口，存到 workflows 分类下
        await bridge.apiPost("save_item", {
          category: "workflows",
          filename: file.name,
          data: parsed
        });

        // 3. 更新本地缓存并渲染 UI
        Store.workflows[file.name] = parsed;
        Utils.showToast(`成功解析并保存工作流: ${file.name}`);
        this.renderWorkflowsSelect();

        if (Store.editingCoreData) {
          Store.editingCoreData.workflows = file.name;
          document.getElementById('core-workflows').value = file.name;
          this.updateNodeDatalist();
        }
      } catch (err) {
        Utils.showToast("JSON 格式错误或保存失败", "error");
        console.error(err);
      }
    };

    // 以纯文本形式读取文件
    reader.readAsText(file);
    event.target.value = ''; // 清空 input
  },

  renderWorkflowsSelect() {
    const select = document.getElementById('core-workflows');
    const currentValue = Store.editingCoreData ? Store.editingCoreData.workflows : '';
    let optionsHtml = `<option value="">-- 请选择工作流 --</option>`;

    Object.keys(Store.workflows).forEach(fileName => {
      optionsHtml += `<option value="${fileName}">${fileName}</option>`;
    });

    select.innerHTML = optionsHtml;
    select.value = currentValue || '';
    this.updateNodeDatalist();
  },

  updateNodeDatalist() {
    const datalist = document.getElementById('workflow-nodes');
    datalist.innerHTML = '';
    const currentWfName = Store.editingCoreData?.workflows;
    if (currentWfName && Store.workflows[currentWfName]) {
      const wf = Store.workflows[currentWfName];
      Object.keys(wf).forEach(nodeId => {
        const nodeType = wf[nodeId].class_type || '';
        datalist.innerHTML += `<option value="${nodeId}">${nodeType}</option>`;
      });
    }
  },

  loadKeysDatalist(nodeIdInput) {
    const nodeId = nodeIdInput.value;
    const datalist = document.getElementById('workflow-keys');
    datalist.innerHTML = '';

    const currentWfName = Store.editingCoreData?.workflows;
    if (currentWfName && Store.workflows[currentWfName]) {
      const wf = Store.workflows[currentWfName];
      if (wf[nodeId] && wf[nodeId].inputs) {
        Object.keys(wf[nodeId].inputs).forEach(key => {
          datalist.innerHTML += `<option value="${key}"></option>`;
        });
      }
    }
  },

  // =====================
  // Core Config 列表管理
  // =====================
  generateEmptyCore() {
    return {
      version: "1.0",
      uuid: Utils.generateUUID(),
      workflows: "",
      commands: "",
      inputs_texts: [],
      inputs_images: [],
      outputs: []
    };
  },

  createNewCore() {
    Store.editingCoreIndex = -1;
    Store.editingCoreData = this.generateEmptyCore();
    this.renderCoreForm();
  },

  editCore(index) {
    Store.editingCoreIndex = index;
    Store.editingCoreData = Utils.deepClone(Store.data.core[index]);
    this.renderCoreForm();
  },

  async copyCore(index) {
    const copied = Utils.deepClone(Store.data.core[index]);
    copied.uuid = Utils.generateUUID();
    copied.inputs_texts.forEach(i => i.uuid = Utils.generateUUID());
    copied.inputs_images.forEach(i => i.uuid = Utils.generateUUID());
    copied.outputs.forEach(i => i.uuid = Utils.generateUUID());
    copied.commands = copied.commands ? copied.commands + " (副本)" : "未命名 (副本)";

    try {
      await bridge.apiPost("save_item", {
        category: "core",
        filename: `${copied.uuid}.json`,
        data: copied
      });

      Store.data.core.push(copied);
      Utils.showToast("配置已复制");
      this.renderView();
    } catch (err) {
      Utils.showToast("复制失败，无法写入服务器文件", "error");
      console.error(err);
    }
  },

  deleteCore(index) {
    Utils.showConfirm("确定要删除此配置及其文件吗？", async () => {
      const targetUuid = Store.data.core[index].uuid;

      try {
        // 告知后端删除对应的文件
        await bridge.apiPost("delete_item", {
          category: "core",
          filename: `${targetUuid}.json`
        });

        // 删除成功后更新前端状态
        Store.data.core.splice(index, 1);
        if (Store.editingCoreIndex === index) {
          Store.editingCoreData = null;
          Store.editingCoreIndex = -1;
        }

        Utils.showToast("配置及文件已删除");
        this.renderView();
      } catch(err) {
        Utils.showToast("从服务器删除文件失败", "error");
      }
    });
  },

  async saveCoreConfig() {
    if (!Store.editingCoreData) return;

    const dataToSave = Store.editingCoreData;
    const filename = `${dataToSave.uuid}.json`; // 使用 UUID 作为文件名

    try {
      // 单独保存这个文件到后端的 configs 目录
      await bridge.apiPost("save_item", {
        category: "core",
        filename: filename,
        data: dataToSave
      });

      // 保存成功后更新本地状态
      if (Store.editingCoreIndex === -1) {
        Store.data.core.push(dataToSave);
      } else {
        Store.data.core[Store.editingCoreIndex] = dataToSave;
      }

      Store.editingCoreData = null;
      Store.editingCoreIndex = -1;

      Utils.showToast("配置已保存");
      this.renderView();
    } catch (err) {
      Utils.showToast("保存到服务器失败", "error");
    }
  },

  // =====================
  // 编辑区的表单更新（此时存在于内存，点击保存时才提交服务器）
  // =====================
  updateEditingCore(fieldName, value) {
    if (Store.editingCoreData) {
      Store.editingCoreData[fieldName] = value;
      if (fieldName === 'workflows') {
        this.updateNodeDatalist();
      }
    }
  },

  addCoreArrayItem(arrayName) {
    const newItem = { uuid: Utils.generateUUID() };
    if (arrayName === 'inputs_texts') {
      Object.assign(newItem, { id: "", var_name: "", key_name: "", default: "", type: "string", required: false });
    } else if (arrayName === 'inputs_images') {
      Object.assign(newItem, { id: "", key_name: "", var_name: "image_input" });
    } else if (arrayName === 'outputs') {
      Object.assign(newItem, { id: "", type: "text", text: "", output_index: 0, fallback_strategy: "ignore" });
    }
    Store.editingCoreData[arrayName].push(newItem);
    this.renderCoreForm();
  },

  deleteCoreArrayItem(arrayName, index) {
    Utils.showConfirm("确定要删除此项吗？", () => {
      Store.editingCoreData[arrayName].splice(index, 1);
      this.renderCoreForm();
    });
  },

  updateCoreArrayItem(arrayName, index, field, value) {
    Store.editingCoreData[arrayName][index][field] = value;
  },

  // =====================
  // 渲染层
  // =====================
  renderView() {
    if (Store.currentTab === 'coreConfig') {
      this.renderCoreList();
      if (Store.editingCoreData) {
        this.renderCoreForm();
      } else {
        document.getElementById('coreEditArea').style.display = 'none';
      }
    }
  },

  renderCoreList() {
    const container = document.getElementById('coreConfigList');
    if (Store.data.core.length === 0) {
      container.innerHTML = '<p class="placeholder-text" style="color:var(--text-secondary)">暂无保存的配置，请新建配置。</p>';
      return;
    }

    container.innerHTML = Store.data.core.map((cfg, index) => `
      <div class="config-card">
        <div class="config-card-info">
          <span class="config-card-title">${cfg.commands || '未命名的触发词配置'}</span>
          <span class="config-card-sub">Workflows: ${cfg.workflows || '未关联'} | ID: ${cfg.uuid}</span>
        </div>
        <div class="config-card-actions">
          <button class="btn btn-sm btn-secondary" onclick="app.editCore(${index})">编辑</button>
          <button class="btn btn-sm btn-secondary" onclick="app.copyCore(${index})">复制</button>
          <button class="btn btn-sm btn-danger" onclick="app.deleteCore(${index})">删除</button>
        </div>
      </div>
    `).join('');
  },

  renderCoreForm() {
    document.getElementById('coreEditArea').style.display = 'block';
    const data = Store.editingCoreData;
    const isNew = Store.editingCoreIndex === -1;
    document.getElementById('coreEditTitle').textContent = isNew ? "新建核心配置" : "编辑核心配置";

    document.getElementById('core-commands').value = data.commands || "";
    this.renderWorkflowsSelect();

    const renderList = (arrayName, containerId, fieldsRenderer) => {
      const container = document.getElementById(containerId);
      container.innerHTML = data[arrayName].map((item, index) => `
        <div class="item-card">
          ${fieldsRenderer(item, index)}
          <div class="item-actions">
            <button class="btn btn-sm btn-danger" onclick="app.deleteCoreArrayItem('${arrayName}', ${index})">删除</button>
          </div>
        </div>
      `).join('');
    };

    renderList('inputs_texts', 'core-inputs-texts-container', (item, i) => `
      <div class="form-group"><label>节点 ID</label>
        <input type="text" class="node-id-input" list="workflow-nodes" value="${item.id}" onchange="app.updateCoreArrayItem('inputs_texts', ${i}, 'id', this.value)" placeholder="选填 / 搜索"></div>
      <div class="form-group"><label>工作流键名 (key_name)</label>
        <input type="text" list="workflow-keys" value="${item.key_name}" onfocus="app.loadKeysDatalist(this.closest('.item-card').querySelector('.node-id-input'))" onchange="app.updateCoreArrayItem('inputs_texts', ${i}, 'key_name', this.value)"></div>
      <div class="form-group"><label>显示变量名 (var_name)</label>
        <input type="text" value="${item.var_name}" onchange="app.updateCoreArrayItem('inputs_texts', ${i}, 'var_name', this.value)"></div>
      <div class="form-group"><label>默认值 (default)</label>
        <input type="text" value="${item.default}" onchange="app.updateCoreArrayItem('inputs_texts', ${i}, 'default', this.value)"></div>
    `);

    renderList('inputs_images', 'core-inputs-images-container', (item, i) => `
      <div class="form-group"><label>节点 ID</label>
        <input type="text" class="node-id-input" list="workflow-nodes" value="${item.id}" onchange="app.updateCoreArrayItem('inputs_images', ${i}, 'id', this.value)"></div>
      <div class="form-group"><label>工作流键名 (key_name)</label>
        <input type="text" list="workflow-keys" value="${item.key_name}" onfocus="app.loadKeysDatalist(this.closest('.item-card').querySelector('.node-id-input'))" onchange="app.updateCoreArrayItem('inputs_images', ${i}, 'key_name', this.value)"></div>
    `);

    renderList('outputs', 'core-outputs-container', (item, i) => `
      <div class="form-group"><label>节点 ID</label>
        <input type="text" list="workflow-nodes" value="${item.id}" onchange="app.updateCoreArrayItem('outputs', ${i}, 'id', this.value)"></div>
      <div class="form-group"><label>类型 (type)</label>
        <input type="text" value="${item.type}" onchange="app.updateCoreArrayItem('outputs', ${i}, 'type', this.value)" placeholder="text 或 image"></div>
      <div class="form-group"><label>前缀文本 (text)</label>
        <input type="text" value="${item.text}" onchange="app.updateCoreArrayItem('outputs', ${i}, 'text', this.value)"></div>
    `);
  },

  // =====================
  // 导入导出模块（导出当前客户端状态）
  // =====================
  exportJSON() {
    const currentKey = Store.currentTab.replace('Config', '');
    const dataToExport = Store.data[currentKey];

    if (currentKey === 'core' && dataToExport.length === 0 && !Store.editingCoreData) {
      Utils.showToast("没有可导出的数据", "error");
      return;
    }

    if (currentKey === 'core' && Store.editingCoreData) {
      Utils.showToast("请先点击表单右上角的【提交并保存】", "error");
      return;
    }

    const jsonStr = JSON.stringify(dataToExport, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `${currentKey}_config_${Date.now()}.json`;
    a.click();

    URL.revokeObjectURL(url);
    Utils.showToast("导出成功！");
  },

  async importJSON(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (e) => {
      try {
        const parsed = JSON.parse(e.target.result);
        const currentKey = Store.currentTab.replace('Config', '');

        if (currentKey === 'core') {
          if (Array.isArray(parsed)) {
            Store.data.core = Store.data.core.concat(parsed);
          } else {
            Store.data.core.push(parsed);
          }
        } else {
          Store.data[currentKey] = parsed;
        }

        // 导入配置合并后，立刻触发一次同步保存到后端
        this.renderView();

      } catch (err) {
        Utils.showToast("JSON 格式错误或不匹配", "error");
      }
      event.target.value = '';
    };
    reader.readAsText(file);
  }
};
window.app = App;
document.addEventListener('DOMContentLoaded', () => { App.init(); });
