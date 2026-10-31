<%
%>
<script type="text/javascript">
<%
cgilua_lp.include("../template/login_js.lp", getfenv(1))
cgilua_lp.include("../template/commpage_status_comm.lp", getfenv(1))
%>
</script>
<%
cgilua_lp.include("../template/common_eventtriggering.lp", _G.getfenv(1))
local usermgrLogicImpl = require("user_mgr.usermgr_logic_impl")
local username, disabled = usermgrLogicImpl:getAutofillUsername()
local password, disabled = usermgrLogicImpl:getAutofillPassword()
%>
<link rel="stylesheet" type="text/css" href="/css/login.css" />
<style>
<%
if require"common_lib.file_utils".isFileExist("../../public/css/pro_style.css") then
cgilua_lp.include("../../public/css/pro_style.css")
end
%>
</style>
<div id="loginWrapper">
<div class="emFont loginTitle">&?login_001;<%=_G.encodeHTML(env.getenv("WEBTitle"))%>&?login_019;</div>
<div id="loginContainer" class="loginContainer">
<input type="hidden" name="_sessionTOKEN" id="_sessionTOKEN" value="<%=token%>"/>
<div class="loginInstCfgArea">
<div class="row">
<label for="Frm_Username" class="left w120">&?public_026;</label>
<div class="right">
<input type="text" name="Frm_Username" id="Frm_Username" autocomplete="off" class="w180" value="<% =_G.encodeHTML(username) %>" <%if disabled then cgilua.put("disabled") end%>/>
</div>
</div>
<div class="row">
<label for="Frm_Password" class="left w120">&?public_027;</label>
<div class="right">
<input type="password" name="Frm_Password" id="Frm_Password" style="font-family: text-security-disc;" autocomplete="off" class="w180 passInvisible" value="<% =_G.encodeHTML(password) %>"/>
</div>
</div>
<div id="login_error" class="errorHint" style="display:none;" aria-live="assertive" aria-atomic="true">
<span id="login_error_span"></span>
<span id="login_error_waittime" value="0"></span>
</div>
</div>
</div>
<div id="loginBtn" class="">
<input type="submit" id="LoginId" class="button login" value="&?login_004;"/>
</div>
</div>
