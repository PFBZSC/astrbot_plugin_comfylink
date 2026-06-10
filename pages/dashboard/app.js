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
    prompt: { version: "1.0", framework: [], description: [], trigger: [] },
    telegram: []
  },
  workflows: {},
  editingCoreIndex: -1,
  editingCoreData: null,
  editingTelegramIndex: -1,
  editingTelegramData: null
};

const App = {
  async init() {
    await bridge.ready();
    this.bindEvents();
    await this.loadDataFromServer();
    this.renderView();
  },

  async loadDataFromServer() {
    try {
      const res = await bridge.apiGet("get_all");
      if (res) {
        if (res.core) Store.data.core = Array.isArray(res.core) ? res.core : Object.values(res.core);
        if (res.telegram) Store.data.telegram = Array.isArray(res.telegram) ? res.telegram : Object.values(res.telegram);
        if (res.workflows) Store.workflows = res.workflows;

        if (res.prompt) {
          let pData = res.prompt;
          if (Array.isArray(pData)) {
            pData = pData[0] || {};
          } else if (pData && !pData.version && Object.keys(pData).length > 0) {
            pData = Object.values(pData)[0] || {};
          }
          Store.data.prompt = {
            version: "1.0",
            framework: pData.framework || [],
            description: pData.description || [],
            trigger: pData.trigger || []
          };
        }
      }
    } catch (err) {
      Utils.showToast("从后端获取数据失败", "error");
    }
  },

  bindEvents() {
    // 标签页切换逻辑
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

    // 导入导出按钮
    document.getElementById('btnExport').addEventListener('click', () => this.exportJSON());
    document.getElementById('btnImport').addEventListener('click', () => document.getElementById('fileInput').click());
    document.getElementById('fileInput').addEventListener('change', (e) => this.importJSON(e));

    // 使用事件代理统一处理所有卡片的 编辑、复制、删除 按钮
    document.addEventListener('click', (e) => {
      if (e.target && e.target.matches('.config-card-actions button')) {
        const action = e.target.dataset.action;
        const category = e.target.dataset.category;
        const index = parseInt(e.target.dataset.index, 10);

        if (category === 'core') {
          if (action === 'edit') this.editCore(index);
          // 加上 .catch() 消除 Promise 被忽略的警告
          if (action === 'copy') this.copyCore(index).catch(console.error);
          if (action === 'delete') this.deleteCore(index);
        } else if (category === 'telegram') {
          if (action === 'edit') this.editTelegram(index);
          // 加上 .catch() 消除 Promise 被忽略的警告
          if (action === 'copy') this.copyTelegram(index).catch(console.error);
          if (action === 'delete') this.deleteTelegram(index);
        }
      }
    });

  },

  // =====================
  // 通用后端保存逻辑
  // =====================
  async saveToBackend(category, dataObj) {
    const filename = `${dataObj.uuid}.json`;
    await bridge.apiPost("save_item", { category, filename, data: dataObj });
  },
  async deleteFromBackend(category, uuid) {
    await bridge.apiPost("delete_item", { category, filename: `${uuid}.json` });
  },

  // =====================
  // 1. Core Config
  // =====================
  generateEmptyCore() {
    return {
      version: "1.0", uuid: Utils.generateUUID(), workflows: "", commands: "", default: "",
      inputs_texts: [], inputs_images: [], outputs: []
    };
  },
  createNewCore() { Store.editingCoreIndex = -1; Store.editingCoreData = this.generateEmptyCore(); this.renderView(); },
  editCore(index) { Store.editingCoreIndex = index; Store.editingCoreData = Utils.deepClone(Store.data.core[index]); this.renderView(); },

  async saveCoreConfig() {
    if (!Store.editingCoreData) return;
    try {
      await this.saveToBackend("core", Store.editingCoreData);
      if (Store.editingCoreIndex === -1) Store.data.core.push(Store.editingCoreData);
      else Store.data.core[Store.editingCoreIndex] = Store.editingCoreData;
      Store.editingCoreData = null; Store.editingCoreIndex = -1;
      Utils.showToast("配置已保存"); this.renderView();
    } catch (e) { Utils.showToast("保存失败", "error"); }
  },
  deleteCore(index) {
    Utils.showConfirm("确定要删除此配置吗？", async () => {
      try {
        await this.deleteFromBackend("core", Store.data.core[index].uuid);
        Store.data.core.splice(index, 1);
        if (Store.editingCoreIndex === index) { Store.editingCoreData = null; Store.editingCoreIndex = -1; }
        Utils.showToast("配置已删除"); this.renderView();
      } catch (e) { Utils.showToast("删除失败", "error"); }
    });
  },
  async copyCore(index) {
    const copied = Utils.deepClone(Store.data.core[index]);
    copied.uuid = Utils.generateUUID(); copied.commands = (copied.commands || "未命名") + " (副本)";
    try {
      await this.saveToBackend("core", copied); Store.data.core.push(copied);
      Utils.showToast("复制成功"); this.renderView();
    } catch (e) { Utils.showToast("复制失败", "error"); }
  },
  updateEditingCore(fieldName, value) {
    if (Store.editingCoreData) {
      Store.editingCoreData[fieldName] = value;
      if (fieldName === 'workflows') this.updateNodeDatalist();
    }
  },
  addCoreArrayItem(arrayName) {
    const newItem = { uuid: Utils.generateUUID() };
    if (arrayName === 'inputs_texts') Object.assign(newItem, { id: "", var_name: "", key_name: "", default: "", type: "string", required: false });
    else if (arrayName === 'inputs_images') Object.assign(newItem, { id: "", key_name: "", var_name: "image_input" });
    else if (arrayName === 'outputs') Object.assign(newItem, { id: "", type: "text", text: "", output_index: 0, fallback_strategy: "ignore" });
    Store.editingCoreData[arrayName].push(newItem); this.renderCoreForm();
  },
  deleteCoreArrayItem(arrayName, index) {
    Utils.showConfirm("确定要删除此项吗？", () => { Store.editingCoreData[arrayName].splice(index, 1); this.renderCoreForm(); });
  },
  updateCoreArrayItem(arrayName, index, field, value) { Store.editingCoreData[arrayName][index][field] = value; },

  // Workflows (Core专属)
  uploadWorkflow(event) {
    const file = event.target.files[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = async (e) => {
      const textResult = e.target.result;
      if (typeof textResult !== 'string') return;

      try {
        const parsed = JSON.parse(textResult);
        await bridge.apiPost("save_item", { category: "workflows", filename: file.name, data: parsed });
        Store.workflows[file.name] = parsed; Utils.showToast(`工作流已保存`);
        if (Store.editingCoreData) {
          Store.editingCoreData.workflows = file.name; this.renderWorkflowsSelect();
        }
      } catch (err) { Utils.showToast("文件错误", "error"); }
    };
    reader.readAsText(file); event.target.value = '';
  },
  renderWorkflowsSelect() {
    const select = document.getElementById('core-workflows');
    if(!select) return;
    const current = Store.editingCoreData?.workflows || '';
    select.innerHTML = `<option value="">-- 请选择工作流 --</option>` +
      Object.keys(Store.workflows).map(name => `<option value="${name}">${name}</option>`).join('');
    select.value = current; this.updateNodeDatalist();
  },
  updateNodeDatalist() {
    const datalist = document.getElementById('workflow-nodes');
    datalist.innerHTML = ''; const wfName = Store.editingCoreData?.workflows;
    if (wfName && Store.workflows[wfName]) {
      Object.keys(Store.workflows[wfName]).forEach(nodeId => {
        const nodeData = Store.workflows[wfName][nodeId] || {};
        const classType = nodeData['_meta']["title"] || '';
        datalist.innerHTML += `<option value="${nodeId}">${classType}</option>`;
      });
    }
  },
  loadKeysDatalist(nodeIdInput) {
    const nodeId = nodeIdInput.value; const datalist = document.getElementById('workflow-keys'); datalist.innerHTML = '';
    const wfName = Store.editingCoreData?.workflows;
    if (wfName && Store.workflows[wfName]?.[nodeId]?.inputs) {
      Object.keys(Store.workflows[wfName][nodeId].inputs).forEach(key => datalist.innerHTML += `<option value="${key}"></option>`);
    }
  },

  // =====================
  // 2. Prompt Config (移除了废弃的未被使用的函数)
  // =====================
  async savePromptConfig() {
    try {
      await bridge.apiPost("save_item", {
        category: "prompt",
        filename: "system.json",
        data: Store.data.prompt
      });
      Utils.showToast("Prompt 独立配置已保存");
    } catch (e) {
      Utils.showToast("保存失败", "error");
    }
  },

  addPromptArrayItem(type) {
    const item = { uuid: Utils.generateUUID(), name: "", text: "", remark: "" };
    if (type === 'framework') item.slots = ["description"];
    if (type === 'description') item.slots = ["trigger"];

    if (!Store.data.prompt[type]) Store.data.prompt[type] = [];
    Store.data.prompt[type].push(item);
    this.renderPromptForm();
  },
  deletePromptArrayItem(type, index) {
    Utils.showConfirm("确定删除此项吗？", () => {
      Store.data.prompt[type].splice(index, 1);
      this.renderPromptForm();
    });
  },
  updatePromptArrayItem(type, index, field, value) {
    Store.data.prompt[type][index][field] = value;
  },

  // =====================
  // 3. Telegram Config
  // =====================
  generateEmptyTelegram() {
    return { version: "1.0", uuid: Utils.generateUUID(), name: "", core_id: "", dialog: [] };
  },

  createNewTelegram() { Store.editingTelegramIndex = -1; Store.editingTelegramData = this.generateEmptyTelegram(); this.renderView(); },
  editTelegram(index) { Store.editingTelegramIndex = index; Store.editingTelegramData = Utils.deepClone(Store.data.telegram[index]); this.renderView(); },

  updateTelegramField(field, value) {
    if (Store.editingTelegramData) {
      Store.editingTelegramData[field] = value;
    }
  },

  renderTelegramCoreSelect() {
    const select = document.getElementById('telegram-core-id');
    if (!select) return;
    const current = Store.editingTelegramData?.core_id || '';
    let optionsHtml = '<option value="">-- 请选择关联的核心配置 --</option>';

    Store.data.core.forEach(core => {
      const displayName = core.commands || `未命名 (UUID: ${core.uuid.substring(0,8)})`;
      optionsHtml += `<option value="${core.uuid}">${displayName}</option>`;
    });

    select.innerHTML = optionsHtml;
    select.value = current;
  },

  async saveTelegramConfig() {
    if (!Store.editingTelegramData) return;
    try {
      await this.saveToBackend("telegram", Store.editingTelegramData);
      if (Store.editingTelegramIndex === -1) Store.data.telegram.push(Store.editingTelegramData);
      else Store.data.telegram[Store.editingTelegramIndex] = Store.editingTelegramData;
      Store.editingTelegramData = null; Store.editingTelegramIndex = -1;
      Utils.showToast("Telegram 配置已保存"); this.renderView();
    } catch (e) { Utils.showToast("保存失败", "error"); }
  },

  deleteTelegram(index) {
    Utils.showConfirm("确定删除该交互配置吗？", async () => {
      try {
        await this.deleteFromBackend("telegram", Store.data.telegram[index].uuid);
        Store.data.telegram.splice(index, 1);
        if (Store.editingTelegramIndex === index) { Store.editingTelegramData = null; Store.editingTelegramIndex = -1; }
        Utils.showToast("删除成功"); this.renderView();
      } catch (e) { Utils.showToast("删除失败", "error"); }
    });
  },

  async copyTelegram(index) {
    const copied = Utils.deepClone(Store.data.telegram[index]); copied.uuid = Utils.generateUUID();
    try {
      await this.saveToBackend("telegram", copied); Store.data.telegram.push(copied);
      Utils.showToast("复制成功"); this.renderView();
    } catch (e) { Utils.showToast("复制失败", "error"); }
  },

  addTelegramDialog() {
    Store.editingTelegramData.dialog.push({
      uuid: Utils.generateUUID(), step_id: "step_" + Utils.generateUUID().substring(0,8),
      text: "", can_input: false, validation: "none", ui_mode: "inline", option: []
    });
    this.renderTelegramForm();
  },
  deleteTelegramDialog(index) {
    Utils.showConfirm("确定删除这个对话节点及其选项吗？", () => { Store.editingTelegramData.dialog.splice(index, 1); this.renderTelegramForm(); });
  },
  updateTelegramDialog(index, field, value) { Store.editingTelegramData.dialog[index][field] = value; },

  addTelegramOption(dialogIndex) {
    Store.editingTelegramData.dialog[dialogIndex].option.push({
      uuid: Utils.generateUUID(), name: "", var_name: "", value: "", next_step: "step_2"
    });
    this.renderTelegramForm();
  },
  deleteTelegramOption(dialogIndex, optIndex) {
    Utils.showConfirm("确定删除该选项吗？", () => { Store.editingTelegramData.dialog[dialogIndex].option.splice(optIndex, 1); this.renderTelegramForm(); });
  },
  updateTelegramOption(dialogIndex, optIndex, field, value) { Store.editingTelegramData.dialog[dialogIndex].option[optIndex][field] = value; },


  // =====================
  // 渲染层视图分配
  // =====================
  renderView() {
    if (Store.currentTab === 'coreConfig') {
      this.renderListUI('core');
      if (Store.editingCoreData) this.renderCoreForm();
      else document.getElementById('coreEditArea').style.display = 'none';
    } else if (Store.currentTab === 'promptConfig') {
      this.renderPromptForm();
    } else if (Store.currentTab === 'telegramConfig') {
      this.renderListUI('telegram');
      if (Store.editingTelegramData) this.renderTelegramForm();
      else document.getElementById('telegramEditArea').style.display = 'none';
    }
  },

  // 通用列表渲染
  renderListUI(category) {
    const container = document.getElementById(`${category}ConfigList`);
    const dataList = Store.data[category];
    if (dataList.length === 0) {
      container.innerHTML = '<p class="placeholder-text" style="color:var(--text-secondary)">暂无保存的配置，请新建。</p>';
      return;
    }
    container.innerHTML = dataList.map((cfg, index) => {
      const titleStr = category === 'core' ? (cfg.commands || '未命名的配置')
                     : category === 'telegram' ? (cfg.name || `未命名交互配置 (UUID: ${cfg.uuid.substring(0,8)})`)
                     : `${category.toUpperCase()} 配置 ${index + 1}`;

      return `
      <div class="config-card">
        <div class="config-card-info">
          <span class="config-card-title">${titleStr}</span>
          <span class="config-card-sub">UUID: ${cfg.uuid}</span>
        </div>
        <div class="config-card-actions">
          <button class="btn btn-sm btn-secondary" data-action="edit" data-category="${category}" data-index="${index}">编辑</button>
          <button class="btn btn-sm btn-secondary" data-action="copy" data-category="${category}" data-index="${index}">复制</button>
          <button class="btn btn-sm btn-danger" data-action="delete" data-category="${category}" data-index="${index}">删除</button>
        </div>
      </div>
    `}).join('');
  },

  // Core 表单渲染
  renderCoreForm() {
    document.getElementById('coreEditArea').style.display = 'block';
    const data = Store.editingCoreData;
    document.getElementById('core-commands').value = data.commands || "";
    document.getElementById('core-default').value = typeof data.default === 'string' ? data.default : (data.default ? JSON.stringify(data.default) : "");
    this.renderWorkflowsSelect();

    const renderList = (arrayName, containerId, fieldsRenderer) => {
      document.getElementById(containerId).innerHTML = data[arrayName].map((item, index) => `
        <div class="item-card">
          ${fieldsRenderer(item, index)}
          <div class="item-actions"><button class="btn btn-sm btn-danger" onclick="app.deleteCoreArrayItem('${arrayName}', ${index})">删除</button></div>
        </div>
      `).join('');
    };

    renderList('inputs_texts', 'core-inputs-texts-container', (item, i) => `
      <div class="form-group"><label>节点 ID</label><input type="text" class="node-id-input" list="workflow-nodes" value="${item.id}" onchange="app.updateCoreArrayItem('inputs_texts', ${i}, 'id', this.value)"></div>
      <div class="form-group"><label>键名 (key_name)</label><input type="text" list="workflow-keys" value="${item.key_name}" onfocus="app.loadKeysDatalist(this.closest('.item-card').querySelector('.node-id-input'))" onchange="app.updateCoreArrayItem('inputs_texts', ${i}, 'key_name', this.value)"></div>
      <div class="form-group"><label>变量名 (var_name)</label><input type="text" value="${item.var_name}" onchange="app.updateCoreArrayItem('inputs_texts', ${i}, 'var_name', this.value)"></div>
      <div class="form-group"><label>默认值 (default)</label><input type="text" value="${item.default}" onchange="app.updateCoreArrayItem('inputs_texts', ${i}, 'default', this.value)"></div>
    `);
    renderList('inputs_images', 'core-inputs-images-container', (item, i) => `
      <div class="form-group"><label>节点 ID</label><input type="text" class="node-id-input" list="workflow-nodes" value="${item.id}" onchange="app.updateCoreArrayItem('inputs_images', ${i}, 'id', this.value)"></div>
      <div class="form-group"><label>键名 (key_name)</label><input type="text" list="workflow-keys" value="${item.key_name}" onfocus="app.loadKeysDatalist(this.closest('.item-card').querySelector('.node-id-input'))" onchange="app.updateCoreArrayItem('inputs_images', ${i}, 'key_name', this.value)"></div>
    `);
    renderList('outputs', 'core-outputs-container', (item, i) => `
      <div class="form-group"><label>节点 ID</label><input type="text" list="workflow-nodes" value="${item.id}" onchange="app.updateCoreArrayItem('outputs', ${i}, 'id', this.value)"></div>
      <div class="form-group"><label>类型 (type)</label><input type="text" value="${item.type}" onchange="app.updateCoreArrayItem('outputs', ${i}, 'type', this.value)" placeholder="text 或 image"></div>
      <div class="form-group"><label>前缀文本 (text)</label><input type="text" value="${item.text}" onchange="app.updateCoreArrayItem('outputs', ${i}, 'text', this.value)"></div>
    `);
  },

  // Prompt 表单渲染
  renderPromptForm() {
    const data = Store.data.prompt;
    const renderItems = (arrayName, containerId) => {
      const arr = data[arrayName] || [];
      document.getElementById(containerId).innerHTML = arr.map((item, i) => `
        <div class="item-card">
          <div class="form-group"><label>名称/触发词 (name)</label>
            <input type="text" value="${item.name || ''}" onchange="app.updatePromptArrayItem('${arrayName}', ${i}, 'name', this.value)"></div>
          <div class="form-group flex-2"><label>模板文本 (text)</label>
            <input type="text" value="${item.text || ''}" onchange="app.updatePromptArrayItem('${arrayName}', ${i}, 'text', this.value)" placeholder="包含 {} 的模板"></div>
          <div class="form-group"><label>备注说明 (remark)</label>
            <input type="text" value="${item.remark || ''}" onchange="app.updatePromptArrayItem('${arrayName}', ${i}, 'remark', this.value)"></div>
          <div class="item-actions">
            <button class="btn btn-sm btn-danger" onclick="app.deletePromptArrayItem('${arrayName}', ${i})">删除</button>
          </div>
        </div>
      `).join('');
    };
    renderItems('framework', 'prompt-framework-container');
    renderItems('description', 'prompt-description-container');
    renderItems('trigger', 'prompt-trigger-container');
  },

  // Telegram 表单渲染
  renderTelegramForm() {
    document.getElementById('telegramEditArea').style.display = 'block';
    const data = Store.editingTelegramData;

    const nameInput = document.getElementById('telegram-name');
    if(nameInput) nameInput.value = data.name || "";

    this.renderTelegramCoreSelect();

    document.getElementById('telegram-dialog-container').innerHTML = data.dialog.map((dlg, dIdx) => `
      <div class="item-card" style="flex-direction: column; align-items: stretch; padding-right: 20px;">
        <div class="form-row" style="margin-bottom: 0;">
          <div class="form-group flex-2"><label>机器人引导语 (text)</label>
            <input type="text" value="${dlg.text}" onchange="app.updateTelegramDialog(${dIdx}, 'text', this.value)"></div>
          <div class="form-group" style="justify-content: center; align-items: center; flex-direction: row; gap: 10px;">
            <label style="margin:0;">允许手打输入 (can_input)</label>
            <input type="checkbox" ${dlg.can_input ? 'checked' : ''} onchange="app.updateTelegramDialog(${dIdx}, 'can_input', this.checked)">
          </div>
          <div class="item-actions" style="position: static; transform: none; margin-left: auto;">
            <button class="btn btn-sm btn-danger" onclick="app.deleteTelegramDialog(${dIdx})">删除该节点</button>
          </div>
        </div>
        <div class="list-section" style="margin-top: 15px; padding: 15px; background: var(--bg-color);">
          <div class="section-header" style="margin-bottom: 10px; border:none; padding:0;">
            <h4 style="margin:0; font-size:14px;">子选项按钮 (option)</h4>
            <button class="btn btn-sm btn-secondary" onclick="app.addTelegramOption(${dIdx})">+ 新增按钮</button>
          </div>
          <div class="items-container">
            ${dlg.option.map((opt, oIdx) => `
              <div class="item-card" style="padding: 10px 80px 10px 10px; margin-bottom: 5px;">
                <div class="form-group"><label>按钮显示名 (name)</label>
                  <input type="text" value="${opt.name}" onchange="app.updateTelegramOption(${dIdx}, ${oIdx}, 'name', this.value)"></div>
                <div class="form-group"><label>传参变量名 (var_name)</label>
                  <input type="text" value="${opt.var_name}" onchange="app.updateTelegramOption(${dIdx}, ${oIdx}, 'var_name', this.value)"></div>
                <div class="form-group flex-2"><label>传递的实际值 (value)</label>
                  <input type="text" value="${opt.value}" onchange="app.updateTelegramOption(${dIdx}, ${oIdx}, 'value', this.value)"></div>
                <div class="item-actions">
                  <button class="btn btn-sm btn-danger" onclick="app.deleteTelegramOption(${dIdx}, ${oIdx})">删除</button>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
    `).join('');
  },

  // =====================
  // 导入与导出模块
  // =====================
  exportJSON() {
    const currentKey = Store.currentTab.replace('Config', '');
    const dataToExport = Store.data[currentKey];

    if ((currentKey === 'core' && Store.editingCoreData) ||
        (currentKey === 'telegram' && Store.editingTelegramData)) {
      Utils.showToast("请先点击表单右上角的【提交并保存】", "error");
      return;
    }

    if (!dataToExport || dataToExport.length === 0 || (currentKey === 'prompt' && !dataToExport.framework)) {
      Utils.showToast("没有可导出的数据", "error");
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
      const textResult = e.target.result;
      if (typeof textResult !== 'string') return;

      try {
        const parsed = JSON.parse(textResult);
        const currentKey = Store.currentTab.replace('Config', '');

        if (currentKey === 'prompt') {
          const pData = Array.isArray(parsed) ? (parsed[0] || {}) : parsed;
          if (pData.framework) Store.data.prompt.framework.push(...pData.framework);
          if (pData.description) Store.data.prompt.description.push(...pData.description);
          if (pData.trigger) Store.data.prompt.trigger.push(...pData.trigger);

          await bridge.apiPost("save_item", { category: "prompt", filename: "system.json", data: Store.data.prompt });
        } else {
          if (Array.isArray(parsed)) {
            Store.data[currentKey] = Store.data[currentKey].concat(parsed);
          } else {
            Store.data[currentKey].push(parsed);
          }
          for(let item of (Array.isArray(parsed) ? parsed : [parsed])) {
            if(!item.uuid) item.uuid = Utils.generateUUID();
            await this.saveToBackend(currentKey, item);
          }
        }

        this.renderView();
        Utils.showToast("导入并合并成功");
      } catch (err) {
        Utils.showToast("JSON 格式错误或不匹配", "error");
      }
      event.target.value = '';
    };
    reader.readAsText(file);
  }
};

window.app = App;

document.addEventListener('DOMContentLoaded', () => {
  App.init().catch(err => {
    console.error("初始化应用失败:", err);
  });
});